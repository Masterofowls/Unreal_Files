# Generates the 120 fps DefaultScalability.ini.
#   python3 Tools/gen_scalability_120fps.py        -> Config/Profiles/120FPS/
#   python3 Tools/gen_scalability_120fps.py ue58   -> Config/Profiles/UE58/120FPS/
# Edit the tables here, not the generated .ini files.
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
UE58 = len(sys.argv) > 1 and sys.argv[1] == "ue58"
# Generates Config/Profiles/120FPS/DefaultScalability.ini.
# Each cvar row is [Low, Medium, High, Epic, Cine]; every cvar is written to
# every tier so switching presets never leaks values.
T = ["0", "1", "2", "3", "Cine"]
G = []  # (group, header comment, [(cvar, values, comment)])

G.append(("ViewDistanceQuality", """Nanite MaxPixelsPerEdge 1 -> 1.5 is hard to see after TSR upscaling and
lowers the number of triangles Nanite rasterizes in dense scenes.
StaticMeshLODDistanceScale > 1 switches non-Nanite meshes to lower LODs
sooner (guide section 16).""", [
 ("r.SkeletalMeshLODBias", [2, 1, 0, 0, 0], ""),
 ("r.ViewDistanceScale", [0.6, 0.85, 1.0, 1.0, 10.0], ""),
 ("r.Nanite.MaxPixelsPerEdge", [2, 1.5, 1, 1, 1], ""),
 ("r.StaticMeshLODDistanceScale", [1.5, 1.25, 1.0, 1.0, 1.0], "non-Nanite LOD switch distance"),
]))

G.append(("AntiAliasingQuality", """TSR at 120 fps accumulates detail twice as fast as at 60 fps, so a lower
internal resolution converges to near-native quality. History stays at 100%
(200% costs ~4x in the history pass).""", [
 ("r.FXAA.Quality", [0, 1, 2, 3, 5], ""),
 ("r.TemporalAA.Quality", [0, 1, 2, 2, 2], ""),
 ("r.TSR.History.R11G11B10", [1, 1, 1, 1, 0], ""),
 ("r.TSR.History.ScreenPercentage", [100, 100, 100, 100, 200], ""),
 ("r.TSR.History.UpdateQuality", [0, 2, 2, 3, 3], ""),
 ("r.TSR.ShadingRejection.Flickering", [0, 1, 1, 1, 1], ""),
 ("r.TSR.RejectionAntiAliasingQuality", [1, 2, 2, 2, 2], ""),
 ("r.TSR.ReprojectionField", [0, 0, 0, 1, 1], ""),
 ("r.TSR.Resurrection", [0, 0, 0, 1, 1], ""),
 ("r.TSR.ThinGeometryDetection", [0, 0, 1, 1, 1], "[5.6+]"),
]))

G.append(("ShadowQuality", """VSM picks shadow resolution from the INTERNAL pixel footprint. At 55-70%
screen percentage shadows are already cheaper, so these tiers use a SMALLER
LOD bias than the 60 fps profile. Don't reduce resolution twice.
Medium keeps VSM + volumetric fog so the lighting looks the same as High.""", [
 ("r.LightFunctionQuality", [0, 1, 1, 1, 1], ""),
 ("r.ShadowQuality", [1, 3, 3, 4, 5], ""),
 ("r.Shadow.CSM.MaxCascades", [1, 3, 3, 4, 10], ""),
 ("r.Shadow.MaxResolution", [512, 1024, 2048, 2048, 4096], ""),
 ("r.Shadow.MaxCSMResolution", [512, 1024, 2048, 2048, 4096], ""),
 ("r.Shadow.RadiusThreshold", [0.06, 0.04, 0.03, 0.02, 0.01], ""),
 ("r.Shadow.DistanceScale", [0.6, 0.9, 1.0, 1.0, 1.0], ""),
 ("r.Shadow.CSM.TransitionScale", [0, 1.0, 1.0, 1.0, 1.0], ""),
 ("r.Shadow.PreShadowResolutionFactor", [0.5, 0.5, 0.5, 1.0, 1.0], ""),
 ("r.DistanceFieldShadowing", [0, 1, 1, 1, 1], ""),
 ("r.VolumetricFog", [0, 1, 1, 1, 1], ""),
 ("r.VolumetricFog.GridPixelSize", [16, 16, 16, 12, 4], ""),
 ("r.VolumetricFog.GridSizeZ", [64, 64, 64, 96, 128], ""),
 ("r.VolumetricFog.HistoryMissSupersampleCount", [4, 4, 4, 8, 16], ""),
 ("r.LightMaxDrawDistanceScale", [0.5, 0.85, 1.0, 1.0, 1.0], ""),
 ("r.CapsuleShadows", [0, 1, 1, 1, 1], ""),
 ("r.Shadow.Virtual.MaxPhysicalPages", [2048, 2048, 4096, 4096, 8192], ""),
 ("r.Shadow.Virtual.ResolutionLodBiasDirectional", [2.0, 1.0, 0.5, 0.0, -1.5], ""),
 ("r.Shadow.Virtual.ResolutionLodBiasDirectionalMoving", [2.5, 1.5, 1.0, 0.5, -1.5], "time-of-day / moving sun"),
 ("r.Shadow.Virtual.ResolutionLodBiasLocal", [2.5, 1.5, 1.0, 0.5, 0.0], ""),
 ("r.Shadow.Virtual.ResolutionLodBiasLocalMoving", [3.0, 2.0, 1.5, 1.0, 0.0], ""),
 ("r.Shadow.Virtual.SMRT.RayCountDirectional", [0, 4, 6, 8, 16], "soft-shadow filtering"),
 ("r.Shadow.Virtual.SMRT.SamplesPerRayDirectional", [0, 2, 3, 4, 8], ""),
 ("r.Shadow.Virtual.SMRT.RayCountLocal", [0, 4, 4, 7, 16], ""),
 ("r.Shadow.Virtual.SMRT.SamplesPerRayLocal", [0, 2, 2, 4, 8], "AMD: 8 -> 2-4 is visually ~identical"),
]))

G.append(("GlobalIlluminationQuality", """Lumen stays ON at Medium. Switching GI off changes the whole look of the
game, which is the biggest visual loss of all. Medium uses the cheapest Lumen
path (global SDF tracing, coarse radiosity, downsampled integration); dynamic
resolution absorbs the rest.
Low (fallback for iGPU / very old GPUs) turns Lumen off.""" + ("""
[5.8] Medium automatically uses LUMEN LITE (Irradiance Field final gather,
r.Lumen.FinalGatherMethod 0, set by BaseScalability): about 2x cheaper than
High. The screen-probe settings below then only apply to High and above.
IntegrateDownsampleFactor is 1 on High, because Epic removed 2 from High in
5.8 (too noisy).""" if UE58 else ""), [
 ("r.DistanceFieldAO", [0, 1, 1, 1, 1], ""),
 ("r.AOQuality", [0, 1, 2, 2, 2], ""),
 ("r.Lumen.DiffuseIndirect.Allow", [0, 1, 1, 1, 1], ""),
 ("r.LumenScene.Radiosity.ProbeSpacing", [16, 16, 8, 4, 4], ""),
 ("r.LumenScene.Radiosity.HemisphereProbeResolution", [3, 3, 3, 4, 8], ""),
 ("r.LumenScene.Radiosity.UpdateFactor", [128, 128, 96, 64, 32], ""),
 ("r.LumenScene.DirectLighting.UpdateFactor", [64, 64, 48, 32, 16], ""),
 ("r.LumenScene.FastCameraMode", [1, 1, 1, 0, 0], ""),
 ("r.Lumen.TraceMeshSDFs.Allow", [0, 0, 0, 1, 1], "global SDF only below Epic"),
 ("r.Lumen.ScreenProbeGather.DownsampleFactor", [32, 32, 32, 16, 8], ""),
 ("r.Lumen.ScreenProbeGather.TracingOctahedronResolution", [8, 8, 8, 8, 16], ""),
 ("r.Lumen.ScreenProbeGather.IrradianceFormat", [1, 1, 1, 0, 0], ""),
 ("r.Lumen.ScreenProbeGather.StochasticInterpolation", [1, 1, 1, 0, 0], ""),
 ("r.Lumen.ScreenProbeGather.SpatialFilterNumPasses", [1, 1, 2, 3, 3], ""),
 ("r.Lumen.ScreenProbeGather.ShortRangeAO", [0, 1, 1, 1, 1], "contact detail, cheap at low res"),
 ("r.Lumen.ScreenProbeGather.IntegrateDownsampleFactor", [2, 2, 1, 1, 1] if UE58 else [2, 2, 2, 1, 1], ""),
 ("r.Lumen.TranslucencyVolume.Enable", [0, 1, 1, 1, 1], ""),
 ("r.Lumen.TranslucencyVolume.GridPixelSize", [64, 64, 64, 32, 32], ""),
 ("r.Lumen.TranslucencyVolume.TraceFromVolume", [0, 0, 0, 1, 1], ""),
]))

G.append(("ReflectionQuality", """Lumen reflections are the most variable Lumen cost (Epic). Rough surfaces
(> clamp) reuse the diffuse GI instead of tracing. Medium keeps Lumen
reflections at half resolution. If Medium misses budget, set Allow=0 here
FIRST (Epic measures ~1 ms saving) and place Sphere Reflection Captures in
key interiors as the fallback.""", [
 ("r.SSR.Quality", [1, 2, 2, 3, 4], ""),
 ("r.SSR.HalfResSceneColor", [1, 1, 0, 0, 0], ""),
 ("r.Lumen.Reflections.Allow", [0, 1, 1, 1, 1], ""),
 ("r.Lumen.Reflections.DownsampleFactor", [2, 2, 2, 1, 1], ""),
 ("r.Lumen.Reflections.MaxRoughnessToTraceClamp", [0.3, 0.3, 0.4, 0.6, 1.0], ""),
 ("r.Lumen.TranslucencyReflections.FrontLayer.Allow", [0, 0, 0, 1, 1], ""),
]))

G.append(("PostProcessQuality", """DOF and motion blur run at internal resolution (cheaper with dynamic res).
Tonemapping, bloom and post materials after the upscaler run at OUTPUT
resolution, so they don't get cheaper. Medium keeps the full tonemapper,
bloom and eye adaptation (the "look"). Only DOF/motion-blur sample counts are
reduced.""" + ("""
[5.8] r.DOF.PreferLowerBitDepth=1 on Low/Medium lowers DOF buffer bandwidth.""" if UE58 else ""), [
 ("r.MotionBlurQuality", [0, 3, 3, 4, 4], ""),
 ("r.MotionBlur.HalfResGather", [1, 1, 1, 0, 0], ""),
 ("r.AmbientOcclusionMipLevelFactor", [1.0, 0.6, 0.6, 0.4, 0.4], ""),
 ("r.AmbientOcclusionMaxQuality", [0, 60, 100, 100, 100], ""),
 ("r.AmbientOcclusionLevels", [0, 1, 1, -1, -1], ""),
 ("r.AmbientOcclusionRadiusScale", [1.2, 1.0, 1.0, 1.0, 1.0], ""),
 ("r.DepthOfFieldQuality", [0, 1, 2, 2, 4], ""),
 ("r.RenderTargetPoolMin", [300, 350, 400, 400, 1000], ""),
 ("r.LensFlareQuality", [0, 0, 2, 2, 3], ""),
 ("r.SceneColorFringeQuality", [0, 1, 1, 1, 1], ""),
 ("r.EyeAdaptationQuality", [0, 2, 2, 2, 2], ""),
 ("r.BloomQuality", [4, 5, 5, 5, 5], ""),
 ("r.FastBlurThreshold", [0, 3, 3, 100, 100], ""),
 ("r.Upscale.Quality", [1, 2, 2, 3, 3], ""),
 ("r.LightShaftQuality", [0, 1, 1, 1, 1], ""),
 ("r.Filter.SizeScale", [0.6, 1, 1, 1, 1], ""),
 ("r.Tonemapper.Quality", [0, 5, 5, 5, 5], ""),
 ("r.SSS.Scale", [0, 1, 1, 1, 1], ""),
 ("r.SSS.SampleSet", [0, 1, 2, 2, 2], ""),
 ("r.SSS.Quality", [0, 0, 1, 1, 1], ""),
 ("r.SSS.HalfRes", [1, 1, 1, 0, 0], ""),
 ("r.DOF.Gather.ResolutionDivisor", [2, 2, 2, 2, 1], ""),
 ("r.DOF.Gather.AccumulatorQuality", [0, 0, 0, 1, 1], ""),
 ("r.DOF.Gather.PostfilterMethod", [2, 2, 1, 1, 1], ""),
 ("r.DOF.Gather.EnableBokehSettings", [0, 0, 0, 1, 1], ""),
 ("r.DOF.Gather.RingCount", [3, 3, 4, 4, 5], ""),
 ("r.DOF.Scatter.ForegroundCompositing", [0, 1, 1, 1, 1], ""),
 ("r.DOF.Scatter.BackgroundCompositing", [0, 1, 1, 2, 2], ""),
 ("r.DOF.Scatter.EnableBokehSettings", [0, 0, 0, 1, 1], ""),
 ("r.DOF.Scatter.MaxSpriteRatio", [0.04, 0.04, 0.04, 0.1, 0.25], ""),
 ("r.DOF.Recombine.Quality", [0, 0, 1, 2, 2], ""),
 ("r.DOF.Recombine.EnableBokehSettings", [0, 0, 0, 1, 1], ""),
 ("r.DOF.TemporalAAQuality", [0, 1, 1, 1, 1], ""),
 ("r.DOF.Kernel.MaxForegroundRadius", [0.006, 0.012, 0.012, 0.025, 0.025], ""),
 ("r.DOF.Kernel.MaxBackgroundRadius", [0.006, 0.012, 0.012, 0.025, 0.025], ""),
] + ([("r.DOF.PreferLowerBitDepth", [1, 1, 0, 0, 0], "")] if UE58 else [])))

G.append(("TextureQuality", """Texture sharpness costs VRAM, not frame time. Medium keeps MipBias 0 (full
detail) and relies on r.Streaming.LimitPoolSizeToVRAM to stay inside 6-8 GB.
High pool = 2500 MB leaves ~3 GB of an 8 GB card for Nanite, VSM, Lumen,
render targets and the OS.""", [
 ("r.Streaming.MipBias", [1, 0, 0, 0, 0], ""),
 ("r.Streaming.PoolSize", [1000, 1600, 2500, 3500, 4000], "MB"),
 ("r.MaxAnisotropy", [4, 8, 16, 16, 16], ""),
 ("r.VT.MaxAnisotropy", [4, 8, 8, 8, 8], ""),
]))

G.append(("EffectsQuality", """Medium keeps High material quality. Optimize the materials themselves
rather than swapping to simpler "Medium" material branches that change the
look.""", [
 ("r.TranslucencyLightingVolumeDim", [24, 32, 48, 64, 64], ""),
 ("r.RefractionQuality", [0, 2, 2, 2, 2], ""),
 ("r.SceneColorFormat", [3, 3, 4, 4, 4], ""),
 ("r.DetailMode", [0, 1, 2, 2, 2], ""),
 ("r.TranslucencyVolumeBlur", [0, 1, 1, 1, 1], ""),
 ("r.MaterialQualityLevel", [0, 1, 1, 1, 1], "1 = High"),
 ("r.EmitterSpawnRateScale", [0.25, 0.5, 0.75, 1.0, 1.0], ""),
 ("r.ParticleLightQuality", [0, 1, 1, 2, 2], ""),
 ("fx.Niagara.QualityLevel", [0, 1, 2, 3, 4], ""),
 ("r.SkyAtmosphere.FastSkyLUT", [1, 1, 1, 1, 0], ""),
 ("r.SkyAtmosphere.AerialPerspectiveLUT.FastApplyOnOpaque", [1, 1, 1, 1, 0], ""),
 ("r.SkyAtmosphere.SampleCountMax", [4, 8, 16, 32, 64], ""),
 ("r.SkyAtmosphere.FastSkyLUT.SampleCountMax", [4, 8, 16, 32, 64], ""),
 ("r.SkyAtmosphere.TransmittanceLUT.UseSmallFormat", [1, 1, 0, 0, 0], ""),
]))

G.append(("FoliageQuality", """Nanite foliage makes density cheap in raster. The real cost is WPO and
VSM invalidation (see guide section 5).""", [
 ("foliage.DensityScale", [0.5, 0.8, 1.0, 1.0, 1.0], ""),
 ("grass.DensityScale", [0.5, 0.8, 1.0, 1.0, 1.0], ""),
 ("foliage.LODDistanceScale", [0.5, 0.85, 1.0, 1.0, 1.0], ""),
]))

G.append(("ShadingQuality", "[5.2+]", [
 ("r.AnisotropicMaterials", [0, 1, 1, 1, 1], ""),
]))

names = {"0": "Low", "1": "Medium", "2": "High", "3": "Epic", "Cine": "Cinematic"}
out = [""";==============================================================================
;  DefaultScalability.ini  -  120 FPS PROFILE  (""" + ("UE 5.8" if UE58 else "UE 5.3 - 5.7") + """)
;==============================================================================
;  Replaces Config/DefaultScalability.ini when your target is 120 fps.
;  Read Docs/120FPS_Guide.md first: config alone cannot hit 120 fps, content
;  budgets and CPU work matter just as much.
;
;  Tier       Hardware (see guide)                         Output / internal
;  Low        iGPU, GTX 10xx - fallback only, Lumen off    1080p / 50-67%
;  Medium     Tier B: RTX 2060/3050, RX 6600, R5 3600      1080p / 55-75%  @120
;  High       Tier A: RTX 4060/3060Ti 8GB, RX 7600, i5-12400 1440p / 55-70% @120
;                                                          1080p / 70-90%  @120
;  Epic       RTX 4070+/RX 7800+ (120) or Tier A (60)      1440p / 67-100%
;  Cine       Movie Render Queue only
;
;  Internal resolution is driven by dynamic resolution (8.33 ms budget), see
;  Config/Profiles/120FPS/DefaultEngine_120FPS.ini.""" + ("""
;  UE 5.8: also merge Config/Profiles/UE58/DefaultEngine_UE58.ini and read
;  Docs/UE58_Guide.md.""" if UE58 else "") + """
;
;  GENERATED FILE: every cvar is present in every tier (no preset leaking).
;  None of these cvars may also appear in DefaultEngine.ini.
;==============================================================================


;------------------------------------------------------------------------------
;  Auto-detect: calibrate these to YOUR tier machines (guide, section 11).
;  Run "synthbenchmark" on a Tier A and a Tier B PC and put the GPU index
;  between them: Tier B lands in Medium (1), Tier A lands in High (2).
;------------------------------------------------------------------------------
[ScalabilitySettings]
PerfIndexThresholds_ResolutionQuality="GPU 150 260 550"
PerfIndexThresholds_GlobalIlluminationQuality="GPU 150 260 550"
PerfIndexThresholds_ReflectionQuality="GPU 150 260 550"
PerfIndexThresholds_PostProcessQuality="GPU 150 260 550"
PerfIndexThresholds_EffectsQuality="GPU 150 260 550"
"""]
for grp, hdr, rows in G:
    out.append("\n;" + "=" * 78)
    out.append(";  " + grp)
    for l in hdr.splitlines():
        out.append(";  " + l)
    out.append(";" + "=" * 78)
    for i, t in enumerate(T):
        out.append(f"; {names[t]}")
        out.append(f"[{grp}@{t}]")
        for cvar, vals, c in rows:
            line = f"{cvar}={vals[i]}"
            out.append(line)
        out.append("")
    # comments for rows collected at end of group header? inline below instead
open(ROOT + "/Config/Profiles/UE58/120FPS/DefaultScalability.ini" if UE58 else ROOT + "/Config/Profiles/120FPS/DefaultScalability.ini", "w").write("\n".join(out).rstrip() + "\n")
