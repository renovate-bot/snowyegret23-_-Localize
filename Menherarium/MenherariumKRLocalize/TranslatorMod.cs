using System.Globalization;
using System.IO;
using HarmonyLib;
using Il2CppChinchiro;
using Il2CppTMPro;
using MelonLoader;
using MelonLoader.Utils;
using UnityEngine;
using UnityEngine.UI;

[assembly: MelonInfo(typeof(Snowyegret.MenherariumTranslator.TranslatorMod), "MenherariumKRLocalize", "1.0.0", "Snowyegret")]
[assembly: MelonGame("Tezcatlipoca", "Menherarium")]

namespace Snowyegret.MenherariumTranslator;

public sealed class TranslatorMod : MelonMod
{
    internal static readonly string RootDir = Path.Combine(MelonEnvironment.ModsDirectory, "MenherariumKRLocalize");
    internal static readonly string ConfigPath = Path.Combine(RootDir, "MenherariumKRLocalize.cfg");
    internal static readonly string TextDumpPath = Path.Combine(RootDir, "text_dump.tsv");
    internal static readonly string TextReplacePath = Path.Combine(RootDir, "text_replace.tsv");
    internal static readonly string DialogueDumpPath = Path.Combine(RootDir, "dialogue_dump.tsv");
    internal static readonly string UiTextDumpPath = Path.Combine(RootDir, "ui_text_dump.tsv");
    internal static readonly string UiTextReplacePath = Path.Combine(RootDir, "ui_text_replace.tsv");
    internal static readonly string SpriteRootPath = Path.Combine(RootDir, "sprites");

    internal static ModConfig Config = new();
    internal static bool SpriteDumpStarted;

    public override void OnInitializeMelon()
    {
        Directory.CreateDirectory(RootDir);
        Config = ModConfig.Load(ConfigPath);

        TextPipeline.Initialize();
        SpritePipeline.Initialize();

        HarmonyInstance.PatchAll(typeof(TranslatorMod).Assembly);

        LoggerInstance.Msg(
            "Config: " +
            $"text_export={Config.TextExport.ToString(CultureInfo.InvariantCulture)}, " +
            $"text_import={Config.TextImport.ToString(CultureInfo.InvariantCulture)}, " +
            $"ui_export={Config.UiExport.ToString(CultureInfo.InvariantCulture)}, " +
            $"ui_import={Config.UiImport.ToString(CultureInfo.InvariantCulture)}, " +
            $"sprite_export={Config.SpriteExport.ToString(CultureInfo.InvariantCulture)}, " +
            $"sprite_import={Config.SpriteImport.ToString(CultureInfo.InvariantCulture)}");
        LoggerInstance.Msg($"Sprite external dump dir: {Config.SpriteExternalDumpDir}");
        LoggerInstance.Msg($"Data path: {RootDir}");
    }
}

[HarmonyPatch(typeof(MasterData), "Awake")]
internal static class PatchMasterDataAwake
{
    private static void Postfix(MasterData __instance)
    {
        try
        {
            TextPipeline.OnMasterDataReady(__instance);
            SpritePipeline.OnMasterDataReady(__instance);
        }
        catch (System.Exception ex)
        {
            MelonLogger.Error($"[Init] MasterData Awake pipeline failed: {ex.Message}");
        }
    }
}

[HarmonyPatch(typeof(TMP_Text), "set_text")]
internal static class PatchTmpTextSetText
{
    private static void Prefix(TMP_Text __instance, ref string value)
    {
        try
        {
            if (string.IsNullOrEmpty(value))
            {
                return;
            }

            TextPipeline.ObserveUiText(__instance, value);

            if (TextPipeline.TryGetUiReplacement(__instance, value, out string replacement))
            {
                value = replacement;
            }
        }
        catch (System.Exception ex)
        {
            MelonLogger.Warning($"[Text] TMP_Text.set_text patch error: {ex.Message}");
        }
    }
}

[HarmonyPatch(typeof(Text), "set_text")]
internal static class PatchUiTextSetText
{
    private static void Prefix(Text __instance, ref string value)
    {
        try
        {
            if (string.IsNullOrEmpty(value))
            {
                return;
            }

            TextPipeline.ObserveUiText(__instance, value);

            if (TextPipeline.TryGetUiReplacement(__instance, value, out string replacement))
            {
                value = replacement;
            }
        }
        catch (System.Exception ex)
        {
            MelonLogger.Warning($"[Text] UI.Text.set_text patch error: {ex.Message}");
        }
    }
}

[HarmonyPatch(typeof(Image), "set_sprite")]
internal static class PatchImageSetSprite
{
    private static void Prefix(ref Sprite value)
    {
        try
        {
            if (value == null)
            {
                return;
            }

            if (SpritePipeline.TryGetReplacement(value, out Sprite replacement))
            {
                value = replacement;
            }
        }
        catch (System.Exception ex)
        {
            MelonLogger.Warning($"[Sprite] Image.set_sprite patch error: {ex.Message}");
        }
    }
}

[HarmonyPatch(typeof(SpriteRenderer), "set_sprite")]
internal static class PatchSpriteRendererSetSprite
{
    private static void Prefix(ref Sprite value)
    {
        try
        {
            if (value == null)
            {
                return;
            }

            if (SpritePipeline.TryGetReplacement(value, out Sprite replacement))
            {
                value = replacement;
            }
        }
        catch (System.Exception ex)
        {
            MelonLogger.Warning($"[Sprite] SpriteRenderer.set_sprite patch error: {ex.Message}");
        }
    }
}

[HarmonyPatch(typeof(AmuletEntity), "LoadIconSprite")]
internal static class PatchAmuletLoadIconSprite
{
    private static void Postfix(ref Sprite __result)
    {
        try
        {
            if (__result == null)
            {
                return;
            }

            if (SpritePipeline.TryGetReplacement(__result, out Sprite replacement))
            {
                __result = replacement;
            }
        }
        catch (System.Exception ex)
        {
            MelonLogger.Warning($"[Sprite] AmuletEntity.LoadIconSprite patch error: {ex.Message}");
        }
    }
}
