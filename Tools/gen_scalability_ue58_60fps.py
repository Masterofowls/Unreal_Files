#   python3 Tools/gen_scalability_ue58_60fps.py  (run after editing Config/DefaultScalability.ini)
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Derives Config/Profiles/UE58/60FPS/DefaultScalability.ini from
# Config/DefaultScalability.ini with the UE 5.8 changes applied.
import re
src = open(ROOT + "/Config/DefaultScalability.ini").read()
s = src

def rep(a, b, count=1):
    global s
    assert s.count(a) >= 1, a[:70]
    s = s.replace(a, b, count)

def set_in_section(section, key, value):
    """Change key=value inside one [section]."""
    global s
    pat = re.compile(r'(\[' + re.escape(section) + r'\]\n(?:(?!\[).*\n)*?)' + re.escape(key) + r'=[^\n]*\n')
    s, n = pat.subn(lambda m: m.group(1) + key + '=' + value + '\n', s)
    assert n == 1, (section, key)

def add_after(section, anchor_key, line):
    global s
    pat = re.compile(r'(\[' + re.escape(section) + r'\]\n(?:(?!\[).*\n)*?' + re.escape(anchor_key) + r'=[^\n]*\n)')
    s, n = pat.subn(lambda m: m.group(1) + line + '\n', s)
    assert n == 1, (section, anchor_key)

rep(";  DefaultScalability.ini  -  Performance-tuned quality tiers (UE 5.3 - 5.7)",
    ";  DefaultScalability.ini  -  Performance-tuned quality tiers (UE 5.8)")
rep(";    Medium : GTX 1660 / RX 580-class, 60 fps. No Lumen (DFAO + SSR instead).",
    ";    Medium : GTX 1660 / RX 580-class, 60 fps. LUMEN LITE (5.8): Irradiance\n"
    ";             Field GI + Lumen reflections, about 2x cheaper than Lumen High.")
rep(";   * Cvars tagged [5.x+] are ignored by older engines.",
    ";   * Cvars tagged [5.x+] are ignored by older engines.\n"
    ";   * UE 5.8 variant of Config/DefaultScalability.ini (see Docs/UE58_Guide.md).\n"
    ";     Differences: Lumen allowed at Medium (-> Lumen Lite), IntegrateDownsample\n"
    ";     removed from High (Epic: too noisy), r.DOF.PreferLowerBitDepth per tier.")
rep(";  GLOBAL ILLUMINATION  (Lumen High+ ; DFAO fallback on Medium)",
    ";  GLOBAL ILLUMINATION  (5.8: Lumen Lite on Medium, Lumen on High+)\n"
    ";  Medium: BaseScalability 5.8 selects the Irradiance Field final gather\n"
    ";  (r.Lumen.FinalGatherMethod 0). The screen-probe keys below only matter on\n"
    ";  High and above. Check in-game: type r.Lumen.FinalGatherMethod at Medium -> 0.")
set_in_section("GlobalIlluminationQuality@1", "r.Lumen.DiffuseIndirect.Allow", "1")
set_in_section("GlobalIlluminationQuality@2", "r.Lumen.ScreenProbeGather.IntegrateDownsampleFactor", "1")
rep(";  REFLECTIONS  (Lumen High+ ; SSR fallback)",
    ";  REFLECTIONS  (5.8: Lumen on Medium+ ; SSR fallback on Low)")
set_in_section("ReflectionQuality@1", "r.Lumen.Reflections.Allow", "1")
for tier, v in (("0", "1"), ("1", "1"), ("2", "0"), ("3", "0"), ("Cine", "0")):
    add_after("PostProcessQuality@" + tier, "r.DOF.Kernel.MaxBackgroundRadius", "r.DOF.PreferLowerBitDepth=" + v)

open(ROOT + "/Config/Profiles/UE58/60FPS/DefaultScalability.ini", "w").write(s)
