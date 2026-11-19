A run = one small JSON config like the ones in this folder 

{"scenario": "gidas_1549178", "controller": "hidrive", "errors": [...], "seed": 42, "dt_s": 0.01}
`config.py` fills in the defaults and checks every value, then run.py does the rest

So the workflow is now: config ─► build scene ─► esmini runs ─► errors per step ─► results
