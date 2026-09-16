# -*- coding: utf-8 -*-
import importlib.util, os, sys, shutil
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location("gh", os.path.join(ROOT, "tools", "gen_height.py"))
gh = importlib.util.module_from_spec(spec); sys.modules["gh"] = gh; spec.loader.exec_module(gh)
np = gh.np
_orig = gh._stamp_ramp
N = [0]
def wrap(*a, **kw):
    N[0] += 1
    if N[0] <= 3:
        print(f"[probe#{N[0]}] ramp={type(a[2]).__name__} shape={getattr(a[2],'shape',None)} "
              f"layer.shape={a[0].shape} nargs={len(a)} kwargs={sorted(kw)}")
        print(f"           u={a[4]} v={a[5]} lv_u={a[6]} lv_v={a[7]} run={a[8]}")
    return _orig(*a, **kw)
gh._stamp_ramp = wrap
print("call 1: prev=None ->", end=" ")
print(gh.carve_ramps.__defaults__)
