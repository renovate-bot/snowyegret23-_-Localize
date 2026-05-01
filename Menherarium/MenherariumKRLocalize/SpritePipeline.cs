using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Text;
using Il2CppChinchiro;
using MelonLoader;
using UnityEngine;

namespace Snowyegret.MenherariumTranslator;

internal static class SpritePipeline
{
    private sealed class SpriteMeta
    {
        public string Key = string.Empty;
        public string FileName = string.Empty;
        public string SpriteName = string.Empty;
        public float PixelsPerUnit = 100f;
        public float PivotX = 0.5f;
        public float PivotY = 0.5f;
    }

    private static readonly Dictionary<string, SpriteMeta> MetaByKey = new(StringComparer.Ordinal);
    private static readonly Dictionary<string, string> KeyBySpriteName = new(StringComparer.OrdinalIgnoreCase);
    private static readonly Dictionary<string, Sprite> ReplacementByKey = new(StringComparer.Ordinal);
    private static readonly Dictionary<string, Texture2D> ReplacementTextureByKey = new(StringComparer.Ordinal);
    private static readonly Dictionary<string, string> ExternalPngBySpriteName = new(StringComparer.OrdinalIgnoreCase);
    private static readonly HashSet<string> FailedReplacementKeys = new(StringComparer.Ordinal);
    private const string AlternateIconSuffix = "_Another";
    private const string NameKeyPrefix = "Name/";
    private static int _encodeErrorLogCount;
    private static int _replaceHitLogCount;

    private static string _dumpDir = string.Empty;
    private static string _replaceDir = string.Empty;
    private static string _indexPath = string.Empty;
    private static bool _indexLoaded;
    private static bool _liveScanStarted;
    private static bool _replacementPreloadStarted;
    private static bool _replacementPreloadDone;
    private static string _externalLanguageVariantPath = string.Empty;
    private static string _externalLanguageVariantDumpDir = string.Empty;

    public static void Initialize()
    {
        _dumpDir = Path.Combine(TranslatorMod.SpriteRootPath, "dump");
        _replaceDir = Path.Combine(TranslatorMod.SpriteRootPath, "replace");
        _indexPath = Path.Combine(TranslatorMod.SpriteRootPath, "index.tsv");
        _externalLanguageVariantPath = Path.Combine(TranslatorMod.RootDir, "sprite_external_variants.tsv");
        _externalLanguageVariantDumpDir = Path.Combine(TranslatorMod.RootDir, "sprite_external_variants");

        if (TranslatorMod.Config.SpriteExport == 1)
        {
            Directory.CreateDirectory(TranslatorMod.SpriteRootPath);
            Directory.CreateDirectory(_dumpDir);
        }

        FailedReplacementKeys.Clear();
        ReplacementByKey.Clear();
        ReplacementTextureByKey.Clear();
        ExternalPngBySpriteName.Clear();
        _replaceHitLogCount = 0;
        LoadIndex();

        if (TranslatorMod.Config.SpriteImport == 1)
        {
            BuildExternalNameIndex();
        }
    }

    public static void OnMasterDataReady(MasterData master)
    {
        if (TranslatorMod.Config.SpriteImport == 1 && !_replacementPreloadStarted)
        {
            _replacementPreloadStarted = true;
            MelonCoroutines.Start(PreloadReplacementSprites());
        }

        if (TranslatorMod.Config.SpriteExport == 1 && !TranslatorMod.SpriteDumpStarted)
        {
            TranslatorMod.SpriteDumpStarted = true;
            MelonCoroutines.Start(DumpFromMasterIconsWhenReady(master));
        }

        if (TranslatorMod.Config.SpriteExport == 1 && !_liveScanStarted)
        {
            _liveScanStarted = true;
            MelonCoroutines.Start(DumpLoadedSpritesAfterDelay());
        }
    }

    public static bool TryGetReplacement(Sprite original, out Sprite replacement)
    {
        replacement = null;
        if (TranslatorMod.Config.SpriteImport != 1 || original == null)
        {
            return false;
        }

        string spriteName = NormalizeSpriteName(original.name);
        // External dump override has highest priority.
        if (TryGetReplacementBySpriteName(spriteName, out replacement, out string externalKey))
        {
            LogReplaceHit(spriteName, externalKey);
            return true;
        }

        if (KeyBySpriteName.TryGetValue(spriteName, out string key) && TryGetReplacementByKey(key, out replacement))
        {
            LogReplaceHit(spriteName, key);
            return true;
        }

        if (TryGetReplacementByKey(spriteName, out replacement))
        {
            LogReplaceHit(spriteName, spriteName);
            return true;
        }

        return false;
    }

    private static bool TryGetReplacementByKey(string key, out Sprite replacement)
    {
        replacement = null;
        string normalized = NormalizeKey(key);
        if (normalized.Length == 0)
        {
            return false;
        }

        if (ReplacementByKey.TryGetValue(normalized, out replacement))
        {
            return true;
        }

        if (FailedReplacementKeys.Contains(normalized))
        {
            return false;
        }

        // Import path uses preloaded cache only.
        if (!_replacementPreloadDone)
        {
            return false;
        }

        return false;
    }

    private static bool TryGetReplacementBySpriteName(string spriteName, out Sprite replacement, out string replacementKey)
    {
        replacement = null;
        replacementKey = string.Empty;

        string normalizedName = NormalizeSpriteName(spriteName);
        if (normalizedName.Length == 0)
        {
            return false;
        }

        string nameKey = BuildNameReplacementKey(normalizedName);
        replacementKey = nameKey;
        if (ReplacementByKey.TryGetValue(nameKey, out replacement))
        {
            return true;
        }

        if (FailedReplacementKeys.Contains(nameKey))
        {
            return false;
        }

        if (!ExternalPngBySpriteName.TryGetValue(normalizedName, out string filePath))
        {
            return false;
        }

        SpriteMeta meta = FindMetaBySpriteName(normalizedName);
        if (!TryCreateReplacementSprite(nameKey, normalizedName, filePath, meta, out Sprite loaded, out string error))
        {
            FailedReplacementKeys.Add(nameKey);
            MelonLogger.Warning($"[Sprite] Name replacement failed sprite='{normalizedName}': {error}");
            return false;
        }

        ReplacementByKey[nameKey] = loaded;
        replacement = loaded;
        MelonLogger.Msg($"[Sprite] Name replacement loaded sprite='{normalizedName}' file='{Path.GetFileName(filePath)}'");
        return true;
    }

    private static void BuildExternalNameIndex()
    {
        string configured = TranslatorMod.Config.SpriteExternalDumpDir ?? string.Empty;
        if (string.IsNullOrWhiteSpace(configured))
        {
            return;
        }

        string root;
        try
        {
            root = ResolveExternalDumpRoot(configured);
        }
        catch (Exception ex)
        {
            MelonLogger.Warning($"[Sprite] External dump path resolve failed. configured='{configured}', error={ex.Message}");
            return;
        }

        if (!Directory.Exists(root))
        {
            MelonLogger.Warning($"[Sprite] External dump directory not found. configured='{configured}', resolved='{root}'");
            return;
        }

        int scanned = 0;
        int indexed = 0;
        int duplicates = 0;
        Dictionary<string, Dictionary<string, (string SpriteName, string FilePath)>> languageGroups = new(StringComparer.OrdinalIgnoreCase);

        try
        {
            foreach (string file in Directory.EnumerateFiles(root, "*.png", SearchOption.AllDirectories))
            {
                if (IsUnderDirectoryNamed(file, "backup"))
                {
                    continue;
                }

                scanned++;

                string spriteName = ExtractSpriteNameFromExternalDump(file);
                if (spriteName.Length == 0)
                {
                    continue;
                }

                if (ExternalPngBySpriteName.ContainsKey(spriteName))
                {
                    duplicates++;
                }
                else
                {
                    ExternalPngBySpriteName[spriteName] = file;
                    indexed++;
                }

                if (!TrySplitLanguageSuffix(spriteName, out string baseName, out string languageTag))
                {
                    continue;
                }

                if (!languageGroups.TryGetValue(baseName, out Dictionary<string, (string SpriteName, string FilePath)> byLanguage))
                {
                    byLanguage = new Dictionary<string, (string SpriteName, string FilePath)>(StringComparer.OrdinalIgnoreCase);
                    languageGroups[baseName] = byLanguage;
                }

                if (!byLanguage.ContainsKey(languageTag))
                {
                    byLanguage[languageTag] = (spriteName, file);
                }
            }
        }
        catch (Exception ex)
        {
            MelonLogger.Warning($"[Sprite] External dump indexing failed: {ex.Message}");
            return;
        }

        MelonLogger.Msg($"[Sprite] External dump indexed. root='{root}', png={scanned.ToString(CultureInfo.InvariantCulture)}, names={indexed.ToString(CultureInfo.InvariantCulture)}, duplicates={duplicates.ToString(CultureInfo.InvariantCulture)}");
        SaveExternalLanguageVariantSnapshot(root, languageGroups);
    }

    private static bool IsUnderDirectoryNamed(string filePath, string directoryName)
    {
        if (string.IsNullOrWhiteSpace(filePath) || string.IsNullOrWhiteSpace(directoryName))
        {
            return false;
        }

        string current = Path.GetDirectoryName(filePath);
        while (!string.IsNullOrEmpty(current))
        {
            string name = Path.GetFileName(current);
            if (string.Equals(name, directoryName, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            string parent = Path.GetDirectoryName(current);
            if (string.Equals(parent, current, StringComparison.Ordinal))
            {
                break;
            }
            current = parent;
        }

        return false;
    }

    private static string ResolveExternalDumpRoot(string configured)
    {
        string expanded = Environment.ExpandEnvironmentVariables((configured ?? string.Empty).Trim());
        if (expanded.Length == 0)
        {
            return string.Empty;
        }

        if (Path.IsPathRooted(expanded))
        {
            return Path.GetFullPath(expanded);
        }

        return Path.GetFullPath(Path.Combine(TranslatorMod.RootDir, expanded));
    }

    private static string ExtractSpriteNameFromExternalDump(string filePath)
    {
        string fileName = Path.GetFileNameWithoutExtension(filePath);
        if (string.IsNullOrWhiteSpace(fileName))
        {
            return string.Empty;
        }

        string value = fileName.Trim();
        int at = value.IndexOf(" @", StringComparison.Ordinal);
        if (at > 0)
        {
            value = value.Substring(0, at).TrimEnd();
        }

        return NormalizeSpriteName(value);
    }

    private static string BuildNameReplacementKey(string spriteName)
    {
        return NameKeyPrefix + spriteName;
    }

    private static SpriteMeta FindMetaBySpriteName(string spriteName)
    {
        if (KeyBySpriteName.TryGetValue(spriteName, out string key) && MetaByKey.TryGetValue(key, out SpriteMeta mapped))
        {
            return mapped;
        }

        foreach (KeyValuePair<string, SpriteMeta> kv in MetaByKey)
        {
            SpriteMeta meta = kv.Value;
            if (meta == null)
            {
                continue;
            }

            string normalizedMetaName = NormalizeSpriteName(meta.SpriteName);
            if (string.Equals(normalizedMetaName, spriteName, StringComparison.OrdinalIgnoreCase))
            {
                return meta;
            }
        }

        return null;
    }

    private static string EscapeField(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return string.Empty;
        }

        return value.Replace("\\", "\\\\")
                    .Replace("\t", "\\t")
                    .Replace("\r", "\\r")
                    .Replace("\n", "\\n");
    }

    private static readonly string[] LanguageSuffixes =
    {
        "_Japanese",
        "_Traditional",
        "_Simplified",
        "_English",
        "_Korean",
        "_Chinese",
        "_JP",
        "_EN",
        "_KR",
        "_CN",
        "_TW",
        "_Jp",
        "_En",
        "_Kr",
        "_Cn",
        "_Tw",
        "_jp",
        "_en",
        "_kr",
        "_cn",
        "_tw",
        "_traditional",
        "_simplified",
        "_japanese",
        "_english",
        "_korean",
        "_chinese"
    };

    private static bool TrySplitLanguageSuffix(string spriteName, out string baseName, out string languageTag)
    {
        baseName = string.Empty;
        languageTag = string.Empty;

        if (string.IsNullOrWhiteSpace(spriteName))
        {
            return false;
        }

        string value = NormalizeSpriteName(spriteName);
        foreach (string suffix in LanguageSuffixes)
        {
            if (!value.EndsWith(suffix, StringComparison.OrdinalIgnoreCase) || value.Length <= suffix.Length)
            {
                continue;
            }

            baseName = value.Substring(0, value.Length - suffix.Length);
            languageTag = suffix.TrimStart('_').ToLowerInvariant();
            if (baseName.Length == 0 || languageTag.Length == 0)
            {
                baseName = string.Empty;
                languageTag = string.Empty;
                return false;
            }

            return true;
        }

        return false;
    }

    private static void SaveExternalLanguageVariantSnapshot(string root, Dictionary<string, Dictionary<string, (string SpriteName, string FilePath)>> groups)
    {
        StringBuilder sb = new();
        sb.AppendLine("GroupKey\tLanguageTag\tSpriteName\tSourcePath");

        if (groups == null || groups.Count == 0)
        {
            File.WriteAllText(_externalLanguageVariantPath, sb.ToString(), new UTF8Encoding(false));
            return;
        }

        Directory.CreateDirectory(_externalLanguageVariantDumpDir);

        int groupCount = 0;
        int copyCount = 0;

        foreach (KeyValuePair<string, Dictionary<string, (string SpriteName, string FilePath)>> groupEntry in groups)
        {
            string groupKey = groupEntry.Key;
            Dictionary<string, (string SpriteName, string FilePath)> byLanguage = groupEntry.Value;
            if (byLanguage == null || byLanguage.Count < 2)
            {
                continue;
            }

            groupCount++;
            foreach (KeyValuePair<string, (string SpriteName, string FilePath)> langEntry in byLanguage)
            {
                string languageTag = langEntry.Key;
                string spriteName = NormalizeSpriteName(langEntry.Value.SpriteName);
                string sourcePath = langEntry.Value.FilePath ?? string.Empty;

                sb.Append(EscapeField(groupKey)).Append('\t')
                  .Append(EscapeField(languageTag)).Append('\t')
                  .Append(EscapeField(spriteName)).Append('\t')
                  .Append(EscapeField(sourcePath))
                  .AppendLine();

                if (!File.Exists(sourcePath))
                {
                    continue;
                }

                string key = $"External/{groupKey}/{languageTag}/{spriteName}";
                string fileName = BuildFileName(key);
                string destination = Path.Combine(_externalLanguageVariantDumpDir, fileName);
                File.Copy(sourcePath, destination, true);
                copyCount++;
            }
        }

        File.WriteAllText(_externalLanguageVariantPath, sb.ToString(), new UTF8Encoding(false));
        MelonLogger.Msg($"[Sprite] External language variants: groups={groupCount.ToString(CultureInfo.InvariantCulture)}, files={copyCount.ToString(CultureInfo.InvariantCulture)}, root='{root}'");
    }

    private static IEnumerator DumpFromMasterIconsWhenReady(MasterData master)
    {
        const int maxAttempts = 120;
        const int reportEvery = 10;

        HashSet<string> keys = new(StringComparer.Ordinal);
        for (int attempt = 1; attempt <= maxAttempts; attempt++)
        {
            keys.Clear();
            CollectMasterIconKeys(master, keys);
            if (keys.Count > 0)
            {
                MelonLogger.Msg($"[Sprite] Key source ready at attempt={attempt.ToString(CultureInfo.InvariantCulture)}");
                MelonLogger.Msg("[Sprite] Waiting 5s for render initialization before dumping...");
                yield return new WaitForSeconds(5f);
                yield return DumpFromMasterIcons(keys);
                yield break;
            }

            if (attempt == 1 || attempt % reportEvery == 0)
            {
                MelonLogger.Msg($"[Sprite] Waiting key sources... attempt={attempt.ToString(CultureInfo.InvariantCulture)}/{maxAttempts.ToString(CultureInfo.InvariantCulture)}");
            }

            yield return new WaitForSeconds(0.5f);
        }

        MelonLogger.Warning("[Sprite] Key sources remained empty. Skipping sprite dump.");
    }

    private static IEnumerator DumpLoadedSpritesAfterDelay()
    {
        // Title/UI sprites may be loaded outside MasterData icon tables.
        yield return new WaitForSeconds(8f);

        Sprite[] sprites = Resources.FindObjectsOfTypeAll<Sprite>();
        if (sprites == null || sprites.Length == 0)
        {
            MelonLogger.Warning("[Sprite] Live scan found no loaded sprites.");
            yield break;
        }

        MelonLogger.Msg($"[Sprite] Live scan start. Loaded count={sprites.Length.ToString(CultureInfo.InvariantCulture)}");

        int dumped = 0;
        for (int i = 0; i < sprites.Length; i++)
        {
            Sprite sprite = sprites[i];
            if (sprite == null)
            {
                continue;
            }

            string key = BuildLiveSpriteKey(sprite);
            if (TryDumpByKey(key, sprite))
            {
                dumped++;
            }

            if ((i + 1) % 100 == 0)
            {
                SaveIndex();
                yield return null;
            }
        }

        SaveIndex();
        MelonLogger.Msg($"[Sprite] Live scan complete. Dumped={dumped.ToString(CultureInfo.InvariantCulture)}");
    }

    private static IEnumerator DumpFromMasterIcons(HashSet<string> keys)
    {
        MelonLogger.Msg($"[Sprite] Dump start. Key count={keys.Count.ToString(CultureInfo.InvariantCulture)}");

        int index = 0;
        int dumped = 0;
        foreach (string key in keys)
        {
            index++;
            Sprite loaded = Resources.Load<Sprite>(key);
            if (loaded != null)
            {
                if (TryDumpByKey(key, loaded))
                {
                    dumped++;
                }
            }
            else if (index <= 20)
            {
                MelonLogger.Warning($"[Sprite] Load failed key='{key}': resource not found.");
            }

            if (index % 25 == 0)
            {
                SaveIndex();
                MelonLogger.Msg($"[Sprite] Progress {index.ToString(CultureInfo.InvariantCulture)}/{keys.Count.ToString(CultureInfo.InvariantCulture)}");
                yield return null;
            }
        }

        SaveIndex();
        MelonLogger.Msg($"[Sprite] Dump complete. Dumped={dumped.ToString(CultureInfo.InvariantCulture)}");
    }

    private static void CollectMasterIconKeys(MasterData master, HashSet<string> keys)
    {
        if (master == null)
        {
            return;
        }

        int before = keys.Count;

        CollectFromAmulets(master.Amulets, keys);
        CollectFromItems(master.Items, keys);
        CollectFromPacks(master.Packs, keys);

        int fieldAdded = keys.Count - before;

        CollectFromAmulets(master.GetAllAmulets(), keys);
        CollectFromItems(master.GetAllItems(), keys);
        CollectFromPacks(master.GetAllPacks(), keys);

        int methodAdded = keys.Count - before - fieldAdded;
        MelonLogger.Msg($"[Sprite] Key sources: fields={fieldAdded.ToString(CultureInfo.InvariantCulture)}, methods={methodAdded.ToString(CultureInfo.InvariantCulture)}");
    }

    private static void AddKey(HashSet<string> keys, string maybeKey)
    {
        string key = NormalizeKey(maybeKey);
        if (key.Length > 0)
        {
            keys.Add(key);
        }
    }

    private static void AddAlternateKey(HashSet<string> keys, string maybeKey)
    {
        string key = NormalizeKey(maybeKey);
        if (key.Length == 0 || key.EndsWith(AlternateIconSuffix, StringComparison.Ordinal))
        {
            return;
        }

        string alternate = key + AlternateIconSuffix;
        if (Resources.Load<Sprite>(alternate) != null)
        {
            keys.Add(alternate);
        }
    }

    private static void CollectFromAmulets(Il2CppSystem.Collections.Generic.List<AmuletEntity> amulets, HashSet<string> keys)
    {
        if (amulets == null)
        {
            return;
        }

        for (int i = 0; i < amulets.Count; i++)
        {
            AmuletEntity item = amulets[i];
            if (item == null)
            {
                continue;
            }

            AddKey(keys, item.Icon);
            AddKey(keys, item.GetIconPath());
            AddAlternateKey(keys, item.Icon);
        }
    }

    private static void CollectFromItems(Il2CppSystem.Collections.Generic.List<ItemEntity> items, HashSet<string> keys)
    {
        if (items == null)
        {
            return;
        }

        for (int i = 0; i < items.Count; i++)
        {
            ItemEntity item = items[i];
            if (item != null)
            {
                AddKey(keys, item.Icon);
                if (item.Code == 9999)
                {
                    AddAlternateKey(keys, item.Icon);
                }
            }
        }
    }

    private static void CollectFromPacks(Il2CppSystem.Collections.Generic.List<PackEntity> packs, HashSet<string> keys)
    {
        if (packs == null)
        {
            return;
        }

        for (int i = 0; i < packs.Count; i++)
        {
            PackEntity item = packs[i];
            if (item != null)
            {
                AddKey(keys, item.Icon);
            }
        }
    }

    private static bool TryDumpByKey(string key, Sprite sprite)
    {
        string normalized = NormalizeKey(key);
        if (normalized.Length == 0 || sprite == null)
        {
            return false;
        }

        string spriteName = NormalizeSpriteName(sprite.name);
        KeyBySpriteName[spriteName] = normalized;

        if (!MetaByKey.TryGetValue(normalized, out SpriteMeta meta))
        {
            meta = new SpriteMeta();
            meta.Key = normalized;
            meta.FileName = BuildFileName(normalized);
            meta.SpriteName = spriteName;
            MetaByKey[normalized] = meta;
        }

        meta.PixelsPerUnit = sprite.pixelsPerUnit;
        meta.PivotX = GetPivotX(sprite);
        meta.PivotY = GetPivotY(sprite);
        if (!string.IsNullOrEmpty(spriteName))
        {
            meta.SpriteName = spriteName;
        }

        byte[] png = EncodeSpritePng(sprite);
        if (png.Length == 0)
        {
            return false;
        }

        string outPath = Path.Combine(_dumpDir, meta.FileName);
        File.WriteAllBytes(outPath, png);
        return true;
    }

    private static byte[] EncodeSpritePng(Sprite sprite)
    {
        Texture2D src = sprite.texture;
        if (src == null)
        {
            return Array.Empty<byte>();
        }

        try
        {
            int texWidth = src.width;
            int texHeight = src.height;
            if (texWidth <= 0 || texHeight <= 0)
            {
                return Array.Empty<byte>();
            }

            Rect rect = sprite.rect;
            int x = Mathf.Clamp(Mathf.RoundToInt(rect.x), 0, texWidth - 1);
            int y = Mathf.Clamp(Mathf.RoundToInt(rect.y), 0, texHeight - 1);
            int w = Mathf.Clamp(Mathf.RoundToInt(rect.width), 1, texWidth - x);
            int h = Mathf.Clamp(Mathf.RoundToInt(rect.height), 1, texHeight - y);

            RenderTexture rt = RenderTexture.GetTemporary(texWidth, texHeight, 0, RenderTextureFormat.ARGB32);
            RenderTexture prev = RenderTexture.active;
            Texture2D readback = new(w, h, TextureFormat.RGBA32, false);
            try
            {
                Graphics.Blit(src, rt);
                RenderTexture.active = rt;
                readback.ReadPixels(new Rect(x, y, w, h), 0, 0);
                readback.Apply(false, false);

                Color32[] pixels = readback.GetPixels32();
                if (pixels == null || pixels.Length != w * h)
                {
                    return Array.Empty<byte>();
                }

                byte[] rgba = ExtractRgba(pixels, w, h, 0, 0, w, h);
                return EncodeRgbaToPng(rgba, w, h);
            }
            finally
            {
                RenderTexture.active = prev;
                RenderTexture.ReleaseTemporary(rt);
                UnityEngine.Object.Destroy(readback);
            }
        }
        catch (Exception ex)
        {
            if (_encodeErrorLogCount < 10)
            {
                _encodeErrorLogCount++;
                string textureName = src != null ? src.name : "null";
                MelonLogger.Warning($"[Sprite] Encode exception key-sprite='{sprite.name}' tex='{textureName}' size={src.width}x{src.height}: {ex.Message}");
            }
            return Array.Empty<byte>();
        }
    }

    private static byte[] ExtractRgba(Color32[] pixels, int texWidth, int texHeight, int x, int y, int w, int h)
    {
        byte[] rgba = new byte[w * h * 4];
        int outIndex = 0;

        // Unity pixel array is bottom-left origin; PNG expects top-left.
        for (int row = h - 1; row >= 0; row--)
        {
            int srcY = y + row;
            int srcBase = srcY * texWidth + x;
            for (int col = 0; col < w; col++)
            {
                Color32 c = pixels[srcBase + col];
                rgba[outIndex++] = c.r;
                rgba[outIndex++] = c.g;
                rgba[outIndex++] = c.b;
                rgba[outIndex++] = c.a;
            }
        }

        return rgba;
    }

    private static byte[] EncodeRgbaToPng(byte[] rgba, int width, int height)
    {
        using MemoryStream ms = new();

        // PNG signature
        ms.Write(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 }, 0, 8);

        // IHDR
        using (MemoryStream ihdr = new())
        {
            WriteInt32BigEndian(ihdr, width);
            WriteInt32BigEndian(ihdr, height);
            ihdr.WriteByte(8); // bit depth
            ihdr.WriteByte(6); // color type RGBA
            ihdr.WriteByte(0); // compression
            ihdr.WriteByte(0); // filter
            ihdr.WriteByte(0); // interlace
            WriteChunk(ms, "IHDR", ihdr.ToArray());
        }

        // IDAT: each row starts with filter byte 0
        int stride = width * 4;
        byte[] scanlines = new byte[(stride + 1) * height];
        int src = 0;
        int dst = 0;
        for (int y = 0; y < height; y++)
        {
            scanlines[dst++] = 0;
            Buffer.BlockCopy(rgba, src, scanlines, dst, stride);
            src += stride;
            dst += stride;
        }

        byte[] compressed;
        using (MemoryStream comp = new())
        {
            using (ZLibStream z = new(comp, System.IO.Compression.CompressionLevel.Optimal, true))
            {
                z.Write(scanlines, 0, scanlines.Length);
            }
            compressed = comp.ToArray();
        }
        WriteChunk(ms, "IDAT", compressed);

        // IEND
        WriteChunk(ms, "IEND", Array.Empty<byte>());

        return ms.ToArray();
    }

    private static void WriteChunk(Stream stream, string type, byte[] data)
    {
        WriteInt32BigEndian(stream, data.Length);
        byte[] typeBytes = Encoding.ASCII.GetBytes(type);
        stream.Write(typeBytes, 0, typeBytes.Length);
        if (data.Length > 0)
        {
            stream.Write(data, 0, data.Length);
        }

        uint crc = Crc32(typeBytes, data);
        WriteInt32BigEndian(stream, unchecked((int)crc));
    }

    private static void WriteInt32BigEndian(Stream stream, int value)
    {
        byte[] bytes =
        {
            (byte)((value >> 24) & 0xFF),
            (byte)((value >> 16) & 0xFF),
            (byte)((value >> 8) & 0xFF),
            (byte)(value & 0xFF)
        };
        stream.Write(bytes, 0, 4);
    }

    private static uint Crc32(byte[] typeBytes, byte[] data)
    {
        uint crc = 0xFFFFFFFFu;
        crc = UpdateCrc32(crc, typeBytes);
        if (data.Length > 0)
        {
            crc = UpdateCrc32(crc, data);
        }
        return ~crc;
    }

    private static uint UpdateCrc32(uint crc, byte[] data)
    {
        const uint poly = 0xEDB88320u;
        for (int i = 0; i < data.Length; i++)
        {
            crc ^= data[i];
            for (int j = 0; j < 8; j++)
            {
                crc = (crc & 1) != 0 ? (crc >> 1) ^ poly : crc >> 1;
            }
        }
        return crc;
    }

    private static IEnumerator PreloadReplacementSprites()
    {
        yield return new WaitForSeconds(1f);

        int candidate = 0;
        int loaded = 0;
        int failed = 0;

        foreach (KeyValuePair<string, SpriteMeta> kv in MetaByKey)
        {
            string key = kv.Key;
            SpriteMeta meta = kv.Value;
            string file = Path.Combine(_replaceDir, meta.FileName);
            if (!File.Exists(file))
            {
                continue;
            }

            candidate++;
            yield return PreloadOneReplacement(key, meta, file, success =>
            {
                if (success)
                {
                    loaded++;
                }
                else
                {
                    failed++;
                }
            });
        }

        _replacementPreloadDone = true;
        MelonLogger.Msg($"[Sprite] Replacement preload complete. candidates={candidate.ToString(CultureInfo.InvariantCulture)}, loaded={loaded.ToString(CultureInfo.InvariantCulture)}, failed={failed.ToString(CultureInfo.InvariantCulture)}");
    }

    private static IEnumerator PreloadOneReplacement(string key, SpriteMeta meta, string filePath, Action<bool> onDone)
    {
        string desiredName = string.IsNullOrEmpty(meta.SpriteName) ? NormalizeSpriteName(key) : NormalizeSpriteName(meta.SpriteName);
        if (!TryCreateReplacementSprite(key, desiredName, filePath, meta, out Sprite loaded, out string error))
        {
            FailedReplacementKeys.Add(key);
            MelonLogger.Warning($"[Sprite] Replacement preload failed key='{key}': {error}");
            onDone(false);
            yield break;
        }

        ReplacementByKey[key] = loaded;
        MelonLogger.Msg($"[Sprite] Replacement preloaded key='{key}' file='{Path.GetFileName(filePath)}'");
        onDone(true);
    }

    private static bool TryCreateReplacementSprite(string cacheKey, string desiredSpriteName, string filePath, SpriteMeta meta, out Sprite sprite, out string error)
    {
        sprite = null;
        error = string.Empty;

        if (!TryDecodePngFile(filePath, out int width, out int height, out byte[] rgba, out string decodeError))
        {
            error = decodeError;
            return false;
        }

        Texture2D tex = new(width, height, TextureFormat.RGBA32, false);
        if (tex == null)
        {
            error = "null texture";
            return false;
        }

        try
        {
            GCHandle pin = GCHandle.Alloc(rgba, GCHandleType.Pinned);
            try
            {
                tex.LoadRawTextureData(pin.AddrOfPinnedObject(), rgba.Length);
                tex.Apply(false, false);
            }
            finally
            {
                pin.Free();
            }

            tex.name = "replacement_" + Path.GetFileNameWithoutExtension(filePath);
            tex.wrapMode = TextureWrapMode.Clamp;
            tex.filterMode = FilterMode.Bilinear;
            UnityEngine.Object.DontDestroyOnLoad(tex);

            float ppu = meta != null && meta.PixelsPerUnit > 0f ? meta.PixelsPerUnit : 100f;
            float pivotX = meta != null ? meta.PivotX : 0.5f;
            float pivotY = meta != null ? meta.PivotY : 0.5f;
            Vector2 pivot = new(Mathf.Clamp01(pivotX), Mathf.Clamp01(pivotY));

            string spriteName = NormalizeSpriteName(desiredSpriteName);
            if (spriteName.Length == 0 && meta != null)
            {
                spriteName = NormalizeSpriteName(meta.SpriteName);
            }
            if (spriteName.Length == 0)
            {
                spriteName = NormalizeSpriteName(Path.GetFileNameWithoutExtension(filePath));
            }

            Sprite created = Sprite.Create(tex, new Rect(0f, 0f, tex.width, tex.height), pivot, ppu);
            created.name = spriteName;
            UnityEngine.Object.DontDestroyOnLoad(created);

            ReplacementTextureByKey[cacheKey] = tex;
            if (!string.IsNullOrEmpty(spriteName))
            {
                KeyBySpriteName[spriteName] = cacheKey;
            }

            sprite = created;
            return true;
        }
        catch (Exception ex)
        {
            UnityEngine.Object.Destroy(tex);
            error = ex.Message;
            return false;
        }
    }

    private static bool TryDecodePngFile(string path, out int width, out int height, out byte[] rgba, out string error)
    {
        width = 0;
        height = 0;
        rgba = Array.Empty<byte>();
        error = string.Empty;

        byte[] png;
        try
        {
            png = File.ReadAllBytes(path);
        }
        catch (Exception ex)
        {
            error = "read error: " + ex.Message;
            return false;
        }

        if (png.Length < 8 ||
            png[0] != 137 || png[1] != 80 || png[2] != 78 || png[3] != 71 ||
            png[4] != 13 || png[5] != 10 || png[6] != 26 || png[7] != 10)
        {
            error = "not a png";
            return false;
        }

        int colorType = -1;
        int bitDepth = -1;
        byte[] palette = null;
        byte[] alphaTable = null;
        bool seenIhdr = false;

        using MemoryStream idat = new();
        int pos = 8;
        while (pos + 8 <= png.Length)
        {
            int chunkLength = ReadInt32BigEndian(png, pos);
            pos += 4;
            if (chunkLength < 0 || pos + 4 + chunkLength + 4 > png.Length)
            {
                error = "invalid chunk length";
                return false;
            }

            string chunkType = Encoding.ASCII.GetString(png, pos, 4);
            pos += 4;

            if (chunkType == "IHDR")
            {
                if (chunkLength < 13)
                {
                    error = "invalid ihdr";
                    return false;
                }

                width = ReadInt32BigEndian(png, pos);
                height = ReadInt32BigEndian(png, pos + 4);
                bitDepth = png[pos + 8];
                colorType = png[pos + 9];
                byte compression = png[pos + 10];
                byte filter = png[pos + 11];
                byte interlace = png[pos + 12];

                if (width <= 0 || height <= 0)
                {
                    error = "invalid image size";
                    return false;
                }

                if (compression != 0 || filter != 0 || interlace != 0)
                {
                    error = "unsupported png mode";
                    return false;
                }

                seenIhdr = true;
            }
            else if (chunkType == "PLTE")
            {
                palette = new byte[chunkLength];
                Buffer.BlockCopy(png, pos, palette, 0, chunkLength);
            }
            else if (chunkType == "tRNS")
            {
                alphaTable = new byte[chunkLength];
                Buffer.BlockCopy(png, pos, alphaTable, 0, chunkLength);
            }
            else if (chunkType == "IDAT")
            {
                idat.Write(png, pos, chunkLength);
            }
            else if (chunkType == "IEND")
            {
                break;
            }

            pos += chunkLength + 4; // data + crc
        }

        if (!seenIhdr)
        {
            error = "missing ihdr";
            return false;
        }

        if (bitDepth != 8)
        {
            error = $"unsupported bit depth: {bitDepth.ToString(CultureInfo.InvariantCulture)}";
            return false;
        }

        int bytesPerPixel = colorType switch
        {
            0 => 1, // grayscale
            2 => 3, // rgb
            3 => 1, // indexed
            4 => 2, // grayscale + alpha
            6 => 4, // rgba
            _ => 0
        };

        if (bytesPerPixel == 0)
        {
            error = $"unsupported color type: {colorType.ToString(CultureInfo.InvariantCulture)}";
            return false;
        }

        if (colorType == 3 && (palette == null || palette.Length == 0))
        {
            error = "indexed png missing palette";
            return false;
        }

        byte[] inflated;
        try
        {
            byte[] compressed = idat.ToArray();
            using MemoryStream input = new(compressed);
            using ZLibStream z = new(input, CompressionMode.Decompress);
            using MemoryStream output = new();
            z.CopyTo(output);
            inflated = output.ToArray();
        }
        catch (Exception ex)
        {
            error = "zlib decode failed: " + ex.Message;
            return false;
        }

        int stride = checked(width * bytesPerPixel);
        int expected = checked((stride + 1) * height);
        if (inflated.Length < expected)
        {
            error = "truncated image data";
            return false;
        }

        byte[] scanline = new byte[stride];
        byte[] prevScanline = new byte[stride];
        byte[] unfiltered = new byte[stride * height];

        int inputPos = 0;
        for (int y = 0; y < height; y++)
        {
            byte filter = inflated[inputPos++];
            Buffer.BlockCopy(inflated, inputPos, scanline, 0, stride);
            inputPos += stride;

            if (!UnfilterScanline(scanline, prevScanline, bytesPerPixel, filter))
            {
                error = $"unsupported filter type: {filter.ToString(CultureInfo.InvariantCulture)}";
                return false;
            }

            Buffer.BlockCopy(scanline, 0, unfiltered, y * stride, stride);

            byte[] temp = prevScanline;
            prevScanline = scanline;
            scanline = temp;
        }

        rgba = new byte[checked(width * height * 4)];
        for (int y = 0; y < height; y++)
        {
            int srcRow = y * stride;
            int dstRow = (height - 1 - y) * width * 4; // Unity raw texture uses bottom-left origin.
            for (int x = 0; x < width; x++)
            {
                int srcIndex = srcRow + x * bytesPerPixel;
                int dstIndex = dstRow + x * 4;

                switch (colorType)
                {
                    case 0:
                    {
                        byte gray = unfiltered[srcIndex];
                        rgba[dstIndex] = gray;
                        rgba[dstIndex + 1] = gray;
                        rgba[dstIndex + 2] = gray;
                        rgba[dstIndex + 3] = 255;
                        break;
                    }
                    case 2:
                        rgba[dstIndex] = unfiltered[srcIndex];
                        rgba[dstIndex + 1] = unfiltered[srcIndex + 1];
                        rgba[dstIndex + 2] = unfiltered[srcIndex + 2];
                        rgba[dstIndex + 3] = 255;
                        break;
                    case 3:
                    {
                        int paletteIndex = unfiltered[srcIndex];
                        int paletteOffset = paletteIndex * 3;
                        if (paletteOffset + 2 >= palette.Length)
                        {
                            error = "palette index out of range";
                            return false;
                        }

                        rgba[dstIndex] = palette[paletteOffset];
                        rgba[dstIndex + 1] = palette[paletteOffset + 1];
                        rgba[dstIndex + 2] = palette[paletteOffset + 2];
                        rgba[dstIndex + 3] = alphaTable != null && paletteIndex < alphaTable.Length ? alphaTable[paletteIndex] : (byte)255;
                        break;
                    }
                    case 4:
                    {
                        byte gray = unfiltered[srcIndex];
                        rgba[dstIndex] = gray;
                        rgba[dstIndex + 1] = gray;
                        rgba[dstIndex + 2] = gray;
                        rgba[dstIndex + 3] = unfiltered[srcIndex + 1];
                        break;
                    }
                    case 6:
                        rgba[dstIndex] = unfiltered[srcIndex];
                        rgba[dstIndex + 1] = unfiltered[srcIndex + 1];
                        rgba[dstIndex + 2] = unfiltered[srcIndex + 2];
                        rgba[dstIndex + 3] = unfiltered[srcIndex + 3];
                        break;
                }
            }
        }

        return true;
    }

    private static bool UnfilterScanline(byte[] scanline, byte[] prev, int bytesPerPixel, byte filterType)
    {
        switch (filterType)
        {
            case 0:
                return true;
            case 1:
                for (int i = 0; i < scanline.Length; i++)
                {
                    int left = i >= bytesPerPixel ? scanline[i - bytesPerPixel] : 0;
                    scanline[i] = unchecked((byte)(scanline[i] + left));
                }
                return true;
            case 2:
                for (int i = 0; i < scanline.Length; i++)
                {
                    scanline[i] = unchecked((byte)(scanline[i] + prev[i]));
                }
                return true;
            case 3:
                for (int i = 0; i < scanline.Length; i++)
                {
                    int left = i >= bytesPerPixel ? scanline[i - bytesPerPixel] : 0;
                    int up = prev[i];
                    scanline[i] = unchecked((byte)(scanline[i] + ((left + up) >> 1)));
                }
                return true;
            case 4:
                for (int i = 0; i < scanline.Length; i++)
                {
                    int left = i >= bytesPerPixel ? scanline[i - bytesPerPixel] : 0;
                    int up = prev[i];
                    int upLeft = i >= bytesPerPixel ? prev[i - bytesPerPixel] : 0;
                    int paeth = PaethPredictor(left, up, upLeft);
                    scanline[i] = unchecked((byte)(scanline[i] + paeth));
                }
                return true;
            default:
                return false;
        }
    }

    private static int PaethPredictor(int a, int b, int c)
    {
        int p = a + b - c;
        int pa = Math.Abs(p - a);
        int pb = Math.Abs(p - b);
        int pc = Math.Abs(p - c);

        if (pa <= pb && pa <= pc)
        {
            return a;
        }

        return pb <= pc ? b : c;
    }

    private static int ReadInt32BigEndian(byte[] data, int offset)
    {
        return (data[offset] << 24) |
               (data[offset + 1] << 16) |
               (data[offset + 2] << 8) |
               data[offset + 3];
    }

    private static void LogReplaceHit(string spriteName, string key)
    {
        if (_replaceHitLogCount >= 20)
        {
            return;
        }

        _replaceHitLogCount++;
        MelonLogger.Msg($"[Sprite] Applied replacement sprite='{spriteName}' key='{key}'");
    }

    private static float GetPivotX(Sprite sprite)
    {
        float width = sprite.rect.width <= 0f ? 1f : sprite.rect.width;
        return Mathf.Clamp01(sprite.pivot.x / width);
    }

    private static float GetPivotY(Sprite sprite)
    {
        float height = sprite.rect.height <= 0f ? 1f : sprite.rect.height;
        return Mathf.Clamp01(sprite.pivot.y / height);
    }

    private static string NormalizeKey(string key)
    {
        return string.IsNullOrWhiteSpace(key) ? string.Empty : key.Trim();
    }

    private static string NormalizeSpriteName(string name)
    {
        if (string.IsNullOrWhiteSpace(name))
        {
            return string.Empty;
        }

        string value = name.Trim();
        if (value.EndsWith("(Clone)", StringComparison.Ordinal))
        {
            value = value.Substring(0, value.Length - 7).TrimEnd();
        }
        return value;
    }

    private static string BuildFileName(string key)
    {
        StringBuilder sb = new();
        foreach (char ch in key)
        {
            if (char.IsLetterOrDigit(ch) || ch == '_' || ch == '-' || ch == '.')
            {
                sb.Append(ch);
            }
            else
            {
                sb.Append('_');
            }
        }

        string baseName = sb.ToString();
        if (baseName.Length > 60)
        {
            baseName = baseName.Substring(0, 60);
        }

        uint hash = Fnv1a(key);
        return $"{baseName}_{hash:x8}.png";
    }

    private static string BuildLiveSpriteKey(Sprite sprite)
    {
        string name = NormalizeSpriteName(sprite.name);
        if (name.Length == 0)
        {
            name = "unnamed";
        }

        Texture2D tex = sprite.texture;
        string texName = tex != null ? NormalizeSpriteName(tex.name) : "notex";
        Rect r = sprite.rect;
        string signature = string.Concat(
            name, "|", texName, "|",
            r.x.ToString("0.###", CultureInfo.InvariantCulture), ",",
            r.y.ToString("0.###", CultureInfo.InvariantCulture), ",",
            r.width.ToString("0.###", CultureInfo.InvariantCulture), ",",
            r.height.ToString("0.###", CultureInfo.InvariantCulture));

        uint hash = Fnv1a(signature);
        return $"Live/{name}/{hash:x8}";
    }

    private static uint Fnv1a(string value)
    {
        const uint offset = 2166136261u;
        const uint prime = 16777619u;
        uint hash = offset;
        foreach (char ch in value)
        {
            hash ^= ch;
            hash *= prime;
        }
        return hash;
    }

    private static void LoadIndex()
    {
        MetaByKey.Clear();
        KeyBySpriteName.Clear();
        _indexLoaded = true;

        if (!File.Exists(_indexPath))
        {
            return;
        }

        foreach (string raw in File.ReadLines(_indexPath, Encoding.UTF8))
        {
            if (string.IsNullOrWhiteSpace(raw) || raw.StartsWith("#", StringComparison.Ordinal) || raw.StartsWith("key\t", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            string[] parts = raw.Split('\t');
            if (parts.Length < 6)
            {
                continue;
            }

            string key = NormalizeKey(parts[0]);
            if (key.Length == 0)
            {
                continue;
            }

            SpriteMeta meta = new();
            meta.Key = key;
            meta.FileName = parts[1];
            meta.PixelsPerUnit = ParseFloat(parts[2], 100f);
            meta.PivotX = ParseFloat(parts[3], 0.5f);
            meta.PivotY = ParseFloat(parts[4], 0.5f);
            meta.SpriteName = parts[5];

            MetaByKey[key] = meta;
            if (!string.IsNullOrEmpty(meta.SpriteName))
            {
                KeyBySpriteName[NormalizeSpriteName(meta.SpriteName)] = key;
            }
        }
    }

    private static float ParseFloat(string value, float fallback)
    {
        return float.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out float parsed) ? parsed : fallback;
    }

    private static void SaveIndex()
    {
        if (!_indexLoaded)
        {
            return;
        }

        StringBuilder sb = new();
        sb.AppendLine("key\tfile\tppu\tpivot_x\tpivot_y\tsprite_name");
        foreach (KeyValuePair<string, SpriteMeta> kv in MetaByKey)
        {
            SpriteMeta meta = kv.Value;
            sb.Append(meta.Key).Append('\t')
              .Append(meta.FileName).Append('\t')
              .Append(meta.PixelsPerUnit.ToString("0.###", CultureInfo.InvariantCulture)).Append('\t')
              .Append(meta.PivotX.ToString("0.######", CultureInfo.InvariantCulture)).Append('\t')
              .Append(meta.PivotY.ToString("0.######", CultureInfo.InvariantCulture)).Append('\t')
              .Append(meta.SpriteName)
              .AppendLine();
        }

        File.WriteAllText(_indexPath, sb.ToString(), new UTF8Encoding(false));
    }
}
