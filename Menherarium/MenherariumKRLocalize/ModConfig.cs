using System;
using System.Globalization;
using System.IO;
using System.Text;

namespace Snowyegret.MenherariumTranslator;

internal sealed class ModConfig
{
    public int TextExport = 0;
    public int TextImport = 0;
    public int UiExport = 0;
    public int UiImport = 1;
    public int SpriteExport = 1;
    public int SpriteImport = 1;
    public string SpriteExternalDumpDir = string.Empty;

    public static ModConfig Load(string path)
    {
        ModConfig cfg = new();
        cfg.SpriteExternalDumpDir = GetDefaultExternalDumpDir();
        if (!File.Exists(path))
        {
            cfg.Save(path);
            return cfg;
        }

        bool hasTextExport = false;
        bool hasTextImport = false;
        bool hasUiExport = false;
        bool hasUiImport = false;
        bool hasSpriteExport = false;
        bool hasSpriteImport = false;
        bool hasSpriteExternalDumpDir = false;

        foreach (string raw in File.ReadLines(path))
        {
            string line = raw.Trim();
            if (line.Length == 0 || line.StartsWith("#", System.StringComparison.Ordinal))
            {
                continue;
            }

            int split = line.IndexOf('=');
            if (split <= 0)
            {
                continue;
            }

            string key = line.Substring(0, split).Trim().ToLowerInvariant();
            string value = line.Substring(split + 1).Trim();

            if (key == "sprite_external_dump_dir")
            {
                cfg.SpriteExternalDumpDir = value;
                hasSpriteExternalDumpDir = true;
                continue;
            }

            if (!int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out int parsed))
            {
                continue;
            }

            if (key == "text_export")
            {
                cfg.TextExport = parsed != 0 ? 1 : 0;
                hasTextExport = true;
                continue;
            }

            if (key == "text_import")
            {
                cfg.TextImport = parsed != 0 ? 1 : 0;
                hasTextImport = true;
                continue;
            }

            if (key == "ui_export")
            {
                cfg.UiExport = parsed != 0 ? 1 : 0;
                hasUiExport = true;
                continue;
            }

            if (key == "ui_import")
            {
                cfg.UiImport = parsed != 0 ? 1 : 0;
                hasUiImport = true;
                continue;
            }

            if (key == "sprite_export")
            {
                cfg.SpriteExport = parsed != 0 ? 1 : 0;
                hasSpriteExport = true;
                continue;
            }

            if (key == "sprite_import")
            {
                cfg.SpriteImport = parsed != 0 ? 1 : 0;
                hasSpriteImport = true;
            }
        }

        if (!hasTextExport || !hasTextImport || !hasUiExport || !hasUiImport || !hasSpriteExport || !hasSpriteImport || !hasSpriteExternalDumpDir)
        {
            cfg.Save(path);
        }

        return cfg;
    }

    public void Save(string path)
    {
        string[] lines =
        {
            "# MenherariumKRLocalize config",
            "# text_export=1 : dump original text/dialogue tsv",
            "# text_import=1 : load text replacement from text_replace.tsv Korean column",
            "# ui_export=1 : dump UI text to ui_text_dump.tsv",
            "# ui_import=1 : load UI replacement from ui_text_replace.tsv Korean column",
            "# sprite_export=1 : dump original sprites",
            "# sprite_import=1 : load replacement sprites",
            "# sprite_external_dump_dir : optional external dump root for name-based sprite import",
            "#  - absolute path: C:\\path\\to\\dump",
            "#  - relative path: ./sprite_external_dump (resolved from Mods\\MenherariumKRLocalize)",
            $"text_export={TextExport.ToString(CultureInfo.InvariantCulture)}",
            $"text_import={TextImport.ToString(CultureInfo.InvariantCulture)}",
            $"ui_export={UiExport.ToString(CultureInfo.InvariantCulture)}",
            $"ui_import={UiImport.ToString(CultureInfo.InvariantCulture)}",
            $"sprite_export={SpriteExport.ToString(CultureInfo.InvariantCulture)}",
            $"sprite_import={SpriteImport.ToString(CultureInfo.InvariantCulture)}",
            $"sprite_external_dump_dir={SpriteExternalDumpDir}"
        };
        File.WriteAllLines(path, lines, new UTF8Encoding(false));
    }

    private static string GetDefaultExternalDumpDir()
    {
        string userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        if (string.IsNullOrWhiteSpace(userProfile))
        {
            return string.Empty;
        }

        return Path.Combine(userProfile, "Downloads", "Menherarium_dump");
    }
}
