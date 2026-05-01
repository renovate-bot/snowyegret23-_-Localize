using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using Il2CppChinchiro;
using Il2CppTMPro;
using MelonLoader;
using UnityEngine;
using UnityEngine.UI;

namespace Snowyegret.MenherariumTranslator;

internal static class TextPipeline
{
    private static readonly Dictionary<int, string> ReplaceByCode = new();
    private static readonly Dictionary<string, string> UiReplaceByOriginal = new(StringComparer.Ordinal);
    private static readonly Dictionary<string, string> UiReplaceByPathAndOriginal = new(StringComparer.Ordinal);
    private static readonly Dictionary<string, (string Path, string Original)> UiDumpRows = new(StringComparer.Ordinal);
    private static bool ReplaceLoaded;
    private static bool DumpComplete;
    private static bool UiDumpDirty;
    private static bool UiBootstrapScanStarted;

    public static void Initialize()
    {
        Directory.CreateDirectory(TranslatorMod.RootDir);
        LoadReplaceTables();
        EnsureUiDumpTemplate();
    }

    public static void OnMasterDataReady(MasterData master)
    {
        try
        {
            if (TranslatorMod.Config.TextExport == 1 && !DumpComplete)
            {
                DumpText(master);
                DumpDialogues(master);
                SaveUiDump(force: true);
                DumpComplete = true;
            }

            if (TranslatorMod.Config.TextImport == 1)
            {
                Apply(master);
            }

            if ((TranslatorMod.Config.UiExport == 1 || TranslatorMod.Config.UiImport == 1) && !UiBootstrapScanStarted)
            {
                UiBootstrapScanStarted = true;
                MelonCoroutines.Start(BootstrapUiScan());
            }
        }
        catch (System.Exception ex)
        {
            MelonLogger.Error($"[Text] OnMasterDataReady failed: {ex.Message}");
        }
    }

    public static bool TryGetReplacement(int code, out string text)
    {
        EnsureReplaceLoaded();
        return ReplaceByCode.TryGetValue(code, out text);
    }

    public static void ObserveUiText(Component component, string text)
    {
        if (TranslatorMod.Config.UiExport != 1)
        {
            return;
        }

        string original = GetValue(text);
        if (!ShouldTrackUiText(original))
        {
            return;
        }

        string path = BuildComponentPath(component);
        if (path.Length == 0)
        {
            return;
        }

        string key = path + "\t" + original;
        if (UiDumpRows.ContainsKey(key))
        {
            return;
        }

        UiDumpRows[key] = (path, original);
        UiDumpDirty = true;
    }

    public static bool TryGetUiReplacement(Component component, string original, out string replacement)
    {
        replacement = string.Empty;
        if (TranslatorMod.Config.UiImport != 1)
        {
            return false;
        }

        EnsureReplaceLoaded();

        string source = GetValue(original);
        if (source.Length == 0)
        {
            return false;
        }

        string path = BuildComponentPath(component);
        if (path.Length > 0)
        {
            string key = path + "\t" + source;
            if (UiReplaceByPathAndOriginal.TryGetValue(key, out replacement) && replacement.Length > 0)
            {
                return true;
            }
        }

        if (UiReplaceByOriginal.TryGetValue(source, out replacement) && replacement.Length > 0)
        {
            return true;
        }

        return false;
    }

    private static IEnumerator BootstrapUiScan()
    {
        const int passCount = 40;
        const float intervalSeconds = 0.5f;

        for (int pass = 1; pass <= passCount; pass++)
        {
            int observed = 0;
            int replaced = 0;

            ScanLoadedTmpTexts(ref observed, ref replaced);
            ScanLoadedLegacyTexts(ref observed, ref replaced);

            if (UiDumpDirty)
            {
                SaveUiDump();
            }

            if (pass == 1 || pass % 10 == 0)
            {
                MelonLogger.Msg(
                    "[Text/UI] Bootstrap scan " +
                    $"{pass.ToString(CultureInfo.InvariantCulture)}/{passCount.ToString(CultureInfo.InvariantCulture)} " +
                    $"observed={observed.ToString(CultureInfo.InvariantCulture)} " +
                    $"replaced={replaced.ToString(CultureInfo.InvariantCulture)} " +
                    $"dump_rows={UiDumpRows.Count.ToString(CultureInfo.InvariantCulture)}");
            }

            yield return new WaitForSeconds(intervalSeconds);
        }

        SaveUiDump(force: true);
        MelonLogger.Msg($"[Text/UI] Bootstrap scan complete. dump_rows={UiDumpRows.Count.ToString(CultureInfo.InvariantCulture)}");
    }

    private static void ScanLoadedTmpTexts(ref int observed, ref int replaced)
    {
        TMP_Text[] texts = Resources.FindObjectsOfTypeAll<TMP_Text>();
        if (texts == null)
        {
            return;
        }

        for (int i = 0; i < texts.Length; i++)
        {
            TMP_Text textComponent = texts[i];
            if (textComponent == null)
            {
                continue;
            }

            string current = GetValue(textComponent.text);
            if (current.Length == 0)
            {
                continue;
            }

            ObserveUiText(textComponent, current);
            observed++;

            if (!TryGetUiReplacement(textComponent, current, out string replacement) ||
                replacement.Length == 0 ||
                string.Equals(replacement, current, StringComparison.Ordinal))
            {
                continue;
            }

            textComponent.text = replacement;
            replaced++;
        }
    }

    private static void ScanLoadedLegacyTexts(ref int observed, ref int replaced)
    {
        Text[] texts = Resources.FindObjectsOfTypeAll<Text>();
        if (texts == null)
        {
            return;
        }

        for (int i = 0; i < texts.Length; i++)
        {
            Text textComponent = texts[i];
            if (textComponent == null)
            {
                continue;
            }

            string current = GetValue(textComponent.text);
            if (current.Length == 0)
            {
                continue;
            }

            ObserveUiText(textComponent, current);
            observed++;

            if (!TryGetUiReplacement(textComponent, current, out string replacement) ||
                replacement.Length == 0 ||
                string.Equals(replacement, current, StringComparison.Ordinal))
            {
                continue;
            }

            textComponent.text = replacement;
            replaced++;
        }
    }

    private static void EnsureReplaceLoaded()
    {
        if (!ReplaceLoaded)
        {
            LoadReplaceTables();
        }
    }

    private static void LoadReplaceTables()
    {
        ReplaceLoaded = true;
        ReplaceByCode.Clear();
        UiReplaceByOriginal.Clear();
        UiReplaceByPathAndOriginal.Clear();

        LoadCodeReplaceTable();
        LoadUiReplaceTable();

        MelonLogger.Msg(
            "[Text] Replace tables loaded: " +
            $"code={ReplaceByCode.Count.ToString(CultureInfo.InvariantCulture)}, " +
            $"ui_original={UiReplaceByOriginal.Count.ToString(CultureInfo.InvariantCulture)}, " +
            $"ui_path={UiReplaceByPathAndOriginal.Count.ToString(CultureInfo.InvariantCulture)}");
    }

    private static void LoadCodeReplaceTable()
    {
        if (!File.Exists(TranslatorMod.TextReplacePath))
        {
            string[] template =
            {
                "# Fill Korean column and save as UTF-8",
                "Code\tJapanese\tEnglish\tSimplified\tTraditional\tKorean\tVoiceFile\tWaitTime"
            };
            File.WriteAllLines(TranslatorMod.TextReplacePath, template, new UTF8Encoding(false));
            return;
        }

        bool headerParsed = false;
        int codeIndex = -1;
        int koreanIndex = -1;

        foreach (string raw in File.ReadLines(TranslatorMod.TextReplacePath, Encoding.UTF8))
        {
            string line = raw.TrimEnd();
            if (line.Length == 0 || line.StartsWith("#", System.StringComparison.Ordinal))
            {
                continue;
            }

            string[] parts = line.Split('\t');
            if (!headerParsed)
            {
                codeIndex = FindColumnIndex(parts, "Code");
                koreanIndex = FindColumnIndex(parts, "Korean");
                if (codeIndex < 0 || koreanIndex < 0)
                {
                    MelonLogger.Warning("[Text] text_replace.tsv header is invalid. Required columns: Code, Korean");
                    return;
                }

                headerParsed = true;
                continue;
            }

            if (codeIndex >= parts.Length || koreanIndex >= parts.Length)
            {
                continue;
            }

            if (!int.TryParse(parts[codeIndex].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out int code))
            {
                continue;
            }

            string translated = Unescape(parts[koreanIndex].Trim());
            if (translated.Length == 0)
            {
                continue;
            }

            ReplaceByCode[code] = translated;
        }

        if (!headerParsed)
        {
            MelonLogger.Warning("[Text] text_replace.tsv is empty or missing header.");
        }
    }

    private static void LoadUiReplaceTable()
    {
        EnsureUiReplaceTemplate();

        int fromDump = LoadUiReplaceRowsFromFile(
            TranslatorMod.UiTextDumpPath,
            "ui_text_dump.tsv",
            warnIfHeaderInvalid: false);

        int fromReplace = LoadUiReplaceRowsFromFile(
            TranslatorMod.UiTextReplacePath,
            "ui_text_replace.tsv",
            warnIfHeaderInvalid: true);

        MelonLogger.Msg(
            "[Text/UI] UI replace sources loaded: " +
            $"ui_text_dump={fromDump.ToString(CultureInfo.InvariantCulture)}, " +
            $"ui_text_replace={fromReplace.ToString(CultureInfo.InvariantCulture)}");
    }

    private static void EnsureUiReplaceTemplate()
    {
        if (File.Exists(TranslatorMod.UiTextReplacePath))
        {
            return;
        }

        string[] template =
        {
            "# UI text replacement table",
            "# Path is optional. If empty, replacement is matched by Original text only.",
            "# You may also fill Korean column in ui_text_dump.tsv and keep text_export=0 for apply-only mode.",
            "Path\tOriginal\tKorean"
        };
        File.WriteAllLines(TranslatorMod.UiTextReplacePath, template, new UTF8Encoding(false));
    }

    private static int LoadUiReplaceRowsFromFile(string path, string fileName, bool warnIfHeaderInvalid)
    {
        if (!File.Exists(path))
        {
            return 0;
        }

        bool headerParsed = false;
        int pathIndex = -1;
        int originalIndex = -1;
        int koreanIndex = -1;
        int loaded = 0;

        foreach (string raw in File.ReadLines(path, Encoding.UTF8))
        {
            string line = raw.TrimEnd();
            if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal))
            {
                continue;
            }

            string[] parts = line.Split('\t');
            if (!headerParsed)
            {
                pathIndex = FindColumnIndex(parts, "Path");
                originalIndex = FindColumnIndex(parts, "Original");
                koreanIndex = FindColumnIndex(parts, "Korean");
                if (originalIndex < 0 || koreanIndex < 0)
                {
                    if (warnIfHeaderInvalid)
                    {
                        MelonLogger.Warning($"[Text] {fileName} header is invalid. Required columns: Original, Korean");
                    }
                    return 0;
                }

                headerParsed = true;
                continue;
            }

            if (originalIndex >= parts.Length || koreanIndex >= parts.Length)
            {
                continue;
            }

            string original = Unescape(parts[originalIndex].Trim());
            string korean = Unescape(parts[koreanIndex].Trim());
            if (original.Length == 0 || korean.Length == 0)
            {
                continue;
            }

            UiReplaceByOriginal[original] = korean;
            loaded++;

            if (pathIndex >= 0 && pathIndex < parts.Length)
            {
                string uiPath = Unescape(parts[pathIndex].Trim());
                if (uiPath.Length > 0)
                {
                    UiReplaceByPathAndOriginal[uiPath + "\t" + original] = korean;
                }
            }
        }

        if (!headerParsed && warnIfHeaderInvalid)
        {
            MelonLogger.Warning($"[Text] {fileName} is empty or missing header.");
        }

        return loaded;
    }

    private static void EnsureUiDumpTemplate()
    {
        if (File.Exists(TranslatorMod.UiTextDumpPath))
        {
            return;
        }

        string[] template =
        {
            "Path\tOriginal\tKorean"
        };
        File.WriteAllLines(TranslatorMod.UiTextDumpPath, template, new UTF8Encoding(false));
    }

    private static void SaveUiDump(bool force = false)
    {
        if (TranslatorMod.Config.UiExport != 1)
        {
            return;
        }

        if (!force && !UiDumpDirty)
        {
            return;
        }

        StringBuilder sb = new();
        sb.AppendLine("Path\tOriginal\tKorean");

        List<string> keys = new(UiDumpRows.Keys);
        keys.Sort(StringComparer.Ordinal);

        for (int i = 0; i < keys.Count; i++)
        {
            string key = keys[i];
            if (!UiDumpRows.TryGetValue(key, out (string Path, string Original) row))
            {
                continue;
            }

            sb.Append(Escape(row.Path)).Append('\t')
              .Append(Escape(row.Original)).Append('\t')
              .AppendLine();
        }

        File.WriteAllText(TranslatorMod.UiTextDumpPath, sb.ToString(), new UTF8Encoding(false));
        UiDumpDirty = false;
    }

    private static bool ShouldTrackUiText(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return false;
        }

        string trimmed = text.Trim();
        if (trimmed.Length == 0 || trimmed.Length > 300)
        {
            return false;
        }

        return true;
    }

    private static string BuildComponentPath(Component component)
    {
        if (component == null)
        {
            return string.Empty;
        }

        Transform transform = component.transform;
        if (transform == null)
        {
            return component.GetType().Name;
        }

        List<string> names = new();
        Transform current = transform;
        while (current != null)
        {
            names.Add(GetValue(current.name));
            current = current.parent;
        }
        names.Reverse();

        string sceneName = "__NoScene";
        GameObject go = component.gameObject;
        if (go != null)
        {
            string candidate = GetValue(go.scene.name);
            if (candidate.Length > 0)
            {
                sceneName = candidate;
            }
        }

        StringBuilder sb = new();
        sb.Append(sceneName);
        for (int i = 0; i < names.Count; i++)
        {
            sb.Append('/');
            sb.Append(names[i]);
        }
        sb.Append('/');
        sb.Append(component.GetType().Name);
        return sb.ToString();
    }

    private static void Apply(MasterData master)
    {
        if (master == null || master.Localizations == null || ReplaceByCode.Count == 0)
        {
            return;
        }

        int changed = 0;
        for (int i = 0; i < master.Localizations.Count; i++)
        {
            LocalizationEntity entry = master.Localizations[i];
            if (entry == null)
            {
                continue;
            }

            if (!ReplaceByCode.TryGetValue(entry.Code, out string translated))
            {
                continue;
            }

            entry.Japanese = translated;
            entry.English = translated;
            entry.Simplified = translated;
            entry.Traditional = translated;
            changed++;
        }

        if (changed > 0)
        {
            MelonLogger.Msg($"[Text] Applied {changed.ToString(CultureInfo.InvariantCulture)} replacements.");
        }
    }

    private static void DumpText(MasterData master)
    {
        if (master == null || master.Localizations == null)
        {
            return;
        }

        StringBuilder sb = new();
        sb.AppendLine("Code\tJapanese\tEnglish\tSimplified\tTraditional\tKorean\tVoiceFile\tWaitTime");
        for (int i = 0; i < master.Localizations.Count; i++)
        {
            LocalizationEntity item = master.Localizations[i];
            if (item == null)
            {
                continue;
            }

            string korean = ReplaceByCode.TryGetValue(item.Code, out string translated) ? translated : string.Empty;

            sb.Append(item.Code.ToString(CultureInfo.InvariantCulture)).Append('\t')
              .Append(Escape(item.Japanese)).Append('\t')
              .Append(Escape(item.English)).Append('\t')
              .Append(Escape(item.Simplified)).Append('\t')
              .Append(Escape(item.Traditional)).Append('\t')
              .Append(Escape(korean)).Append('\t')
              .Append(Escape(item.VoiceFile)).Append('\t')
              .Append(item.WaitTime.ToString("0.###", CultureInfo.InvariantCulture))
              .AppendLine();
        }

        File.WriteAllText(TranslatorMod.TextDumpPath, sb.ToString(), new UTF8Encoding(false));
        MelonLogger.Msg($"[Text] Dump written: {TranslatorMod.TextDumpPath}");
    }

    private static void DumpDialogues(MasterData master)
    {
        if (master == null || master.Dialogues == null)
        {
            return;
        }

        Dictionary<int, LocalizationEntity> localizationByCode = BuildLocalizationMap(master);

        StringBuilder sb = new();
        sb.AppendLine("DialogueCode\tType\tDialogueCodes\tJapanese\tEnglish\tSimplified\tTraditional\tKorean\tVoiceFile\tWaitTime");

        for (int i = 0; i < master.Dialogues.Count; i++)
        {
            DialogueEntity dialogue = master.Dialogues[i];
            if (dialogue == null)
            {
                continue;
            }

            StringBuilder codeList = new();
            StringBuilder japanese = new();
            StringBuilder english = new();
            StringBuilder simplified = new();
            StringBuilder traditional = new();
            StringBuilder korean = new();
            StringBuilder voiceFile = new();
            StringBuilder waitTime = new();

            if (dialogue.DialogueCodes != null)
            {
                for (int j = 0; j < dialogue.DialogueCodes.Count; j++)
                {
                    int code = dialogue.DialogueCodes[j];

                    if (j > 0)
                    {
                        codeList.Append(',');
                    }
                    codeList.Append(code.ToString(CultureInfo.InvariantCulture));

                    localizationByCode.TryGetValue(code, out LocalizationEntity loc);

                    AppendJoined(japanese, Escape(GetValue(loc?.Japanese)));
                    AppendJoined(english, Escape(GetValue(loc?.English)));
                    AppendJoined(simplified, Escape(GetValue(loc?.Simplified)));
                    AppendJoined(traditional, Escape(GetValue(loc?.Traditional)));

                    string koreanValue = ReplaceByCode.TryGetValue(code, out string translated) ? translated : string.Empty;
                    AppendJoined(korean, Escape(koreanValue));

                    AppendJoined(voiceFile, Escape(GetValue(loc?.VoiceFile)));

                    string wait = string.Empty;
                    if (loc != null)
                    {
                        wait = loc.WaitTime.ToString("0.###", CultureInfo.InvariantCulture);
                    }
                    AppendJoined(waitTime, wait);
                }
            }

            sb.Append(dialogue.Code.ToString(CultureInfo.InvariantCulture)).Append('\t')
              .Append(dialogue.Type.ToString()).Append('\t')
              .Append(codeList.ToString()).Append('\t')
              .Append(japanese.ToString()).Append('\t')
              .Append(english.ToString()).Append('\t')
              .Append(simplified.ToString()).Append('\t')
              .Append(traditional.ToString()).Append('\t')
              .Append(korean.ToString()).Append('\t')
              .Append(voiceFile.ToString()).Append('\t')
              .Append(waitTime.ToString())
              .AppendLine();
        }

        File.WriteAllText(TranslatorMod.DialogueDumpPath, sb.ToString(), new UTF8Encoding(false));
        MelonLogger.Msg($"[Text] Dialogue dump written: {TranslatorMod.DialogueDumpPath}");
    }

    private static Dictionary<int, LocalizationEntity> BuildLocalizationMap(MasterData master)
    {
        Dictionary<int, LocalizationEntity> map = new();
        if (master == null || master.Localizations == null)
        {
            return map;
        }

        for (int i = 0; i < master.Localizations.Count; i++)
        {
            LocalizationEntity item = master.Localizations[i];
            if (item == null)
            {
                continue;
            }

            map[item.Code] = item;
        }

        return map;
    }

    private static int FindColumnIndex(string[] columns, string columnName)
    {
        for (int i = 0; i < columns.Length; i++)
        {
            if (string.Equals(columns[i].Trim(), columnName, System.StringComparison.OrdinalIgnoreCase))
            {
                return i;
            }
        }

        return -1;
    }

    private static string GetValue(string value)
    {
        return value ?? string.Empty;
    }

    private static void AppendJoined(StringBuilder sb, string value)
    {
        if (sb.Length > 0)
        {
            sb.Append(" || ");
        }

        sb.Append(value);
    }

    private static string Escape(string text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return string.Empty;
        }

        return text.Replace("\\", "\\\\").Replace("\t", "\\t").Replace("\r", "\\r").Replace("\n", "\\n");
    }

    private static string Unescape(string text)
    {
        return text.Replace("\\n", "\n").Replace("\\r", "\r").Replace("\\t", "\t").Replace("\\\\", "\\");
    }
}
