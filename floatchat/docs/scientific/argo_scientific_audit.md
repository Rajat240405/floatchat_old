# Argo Scientific Audit

**Project:** FloatChat  
**Date:** 2026-07-09  
**Scope:** Argo data model, GDAC indexes, NetCDF formats, variable semantics, QC, data modes, regional definitions, architectural assumptions.

---

## 1. Executive Summary

FloatChat currently uses a single GDAC index `argo_bio-profile_index.txt.gz` to answer all queries, including core variables `TEMP` and `PSAL`. Live index analysis proves this index contains **0 rows with exact `TEMP` or `PSAL`** (401,749 rows scanned). All `TEMP` matches are false positives via substring matching against intermediate diagnostics `TEMP_DOXY`, `TEMP_PH`, etc.

B-Argo files (BR/BD) by specification contain **only** `PRES` + BGC variables + intermediates, never core `TEMP/PSAL/CNDC`. Core variables reside in `R/D` files and merged core+BGC resides in synthetic `SR/SD` files indexed separately.

The audit identifies 11 incorrect assumptions, 9 metadata issues, 10 NetCDF reader issues, and provides a prioritized remediation roadmap.

Related documents:
- Root cause analysis: `../investigations/temp_query_root_cause.md`
- Data model reference: `../architecture/argo_data_model.md`

---

## 2. Argo Ecosystem

Argo is a global array of ~4,000 autonomous profiling floats.

Components:
- **Float:** Apex, Navis, Provor, etc. Platform with CTD + optional BGC sensors.
- **DAC:** Data Assembly Centre (AOML, Coriolis, etc.) that decodes telemetry, creates NetCDF, applies RT QC.
- **GDAC:** Global Data Assembly Centre (Ifremer `https://data-argo.ifremer.fr`, USGODAE). Distributes DAC files via `dac/`, `geo/`, `latest_data/` and index files.
- **Data modes:** `R` real-time (<12h, auto QC), `A` adjusted real-time (RT with previous DM offset), `D` delayed-mode (expert QC, 12 months core, 5-6 cycles BGC).

Index files (compressed ASCII CSV):
- `ar_index_global_prof.txt.gz` – core profile index (R/D)
- `argo_bio-profile_index.txt.gz` – B-Argo profile index (BR/BD) – FloatChat current
- `argo_synthetic-profile_index.txt.gz` – Synthetic merged index (SR/SD) – contains core+ BGC
- `ar_index_global_traj`, `ar_index_global_meta`, `ar_index_global_tech`

Reference: User Manual v3.44 §2.7, §4.1, DOI 10.13155/29825.

---

## 3. Core, BGC, Synthetic Profiles

### 3.1 File Naming

```
<R/D><WMO>_<CYCLE>[D].nc   – Core: R1900045_083.nc, D1900045_003.nc
B<R/D><WMO>_<CYCLE>[D].nc  – BGC: BR1900045_083.nc, BD1900045_003.nc
S<R/D><WMO>_<CYCLE>[D].nc  – Synthetic: SR1900045_083.nc, SD1900045_003.nc
<WMO>_meta.nc, <WMO>_tech.nc, <WMO>_<R/D>traj.nc
```

`B`: B-Argo prefix. `S`: Synthetic prefix. `R/D`: real-time / delayed-mode. `D` suffix after cycle indicates descending profile. Cycle zero-padded 3 digits, 4 digits >999.

### 3.2 Content

**Core (R/D):**
- Dimensions `N_PROF` (1…n, multiple profiles per cycle if bouncing/high-res), `N_LEVELS`.
- Variables: `PRES, TEMP, PSAL, CNDC` + QC, ADJUSTED, ADJUSTED_QC, ADJUSTED_ERROR, PROFILE_*_QC.
- No BGC.

**BGC B-file (BR/BD):**
- Per spec §4.1.2.1: *contains all parameters except core TEMP, PSAL, CNDC*.
- Contains: `PRES` (shared from core) + BGC primary (`DOXY, CHLA, BBP700, BBP532, BBP470, NITRATE, PH_IN_SITU_TOTAL, CDOM, DOWNWELLING_PAR, DOWN_IRRADIANCE{380,412,490,443}, TURBIDITY, CP660, BISULFIDE...`) + intermediates (`TEMP_DOXY, C1PHASE_DOXY, BPHASE_DOXY, PHASE_DELAY_DOXY, FLUORESCENCE_CHLA, BETA_BACKSCATTERING700, VRS_PH, TEMP_PH, UV_INTENSITY_NITRATE...` and `_STD/_MED` burst diagnostics).
- Live verification: `BD1900722_001.nc` vars `PRES,TEMP_DOXY,BPHASE_DOXY,DOXY`. `BD1902453_004.nc` 127 vars, `TEMP,PSAL` absent, `TEMP_DOXY` present.
- Synthetic intermediates ignored in S-files.

**Synthetic S-file (SR/SD):**
- GDAC merges corresponding R/D + BR/BD on common PRES axis: sorted union of distinct valid pressures (QC 1,2,5,8). `N_PROF=1` in v2.
- Contains: `PRES,TEMP,PSAL` + BGC primary, both with QC/ADJUSTED families, plus `*_dPRES` auxiliary indicating distance from original sampling.
- Live verification: `SD1902453_004.nc` vars `PRES,TEMP,PSAL,DOXY,CHLA,BBP700,CDOM,PH_IN_SITU_TOTAL,NITRATE`, `TEMP` and `PSAL` present, `PARAMETER = PRES,TEMP,PSAL,DOXY...`.

### 3.3 Profile Lifecycle

- Cycle 0: surface drift, tech/config, may have subsurface test profile. Short.
- Cycle N: park (~1000 dbar) → descend to max (~2000 dbar) → ascent sampling → surface transmit (JULD, LAT, LON). 10-day nominal, BGC may be faster.
- One cycle may produce multiple profiles (N_PROF>1) if vertical sampling scheme differs per sensor (e.g., DOXY sampled at different depths than CTD). Users must search all N_PROF.

---

## 4. Variables, QC, Adjusted Values, Data Modes

### 4.1 Variable Families

For canonical `X` (e.g., TEMP, DOXY):
```
X(N_PROF,N_LEVELS)              raw telemetered
X_QC                            char flags Table 2
X_ADJUSTED                      calibrated, scientifically preferred
X_ADJUSTED_QC                   QC for adjusted
X_ADJUSTED_ERROR                float uncertainty from DMQC
PROFILE_X_QC                    global profile flag Table 2a (A=100% good .. F=0%)
```

`PARAMETER` (N_PROF,N_PARAM,STRING16) lists params in file. `PARAMETER_DATA_MODE` per param per profile: `R/A/D`.

### 4.2 QC Flags (Table 2)

- `0` no QC, `1` good, `2` probably good, `3` probably bad but correctable, `4` bad not usable, `5` changed, `8` estimated, `9` missing.
- Best practice: use QC 1,2,5,8 for science. QC 3 requires ADJUSTED. QC 4 discard.
- Example rule: if `TEMP_QC=4` or `PRES_QC=4` then `DOXY_QC=4`; if `PSAL_QC=4` then `DOXY_QC=3`.

### 4.3 Adjusted Variables

- Real-time `R`: ADJUSTED often FillValue 99999.
- Adjusted RT `A`: auto offset from previous DM.
- Delayed-mode `D`: expert calibration. Always prefer ADJUSTED when `PARAMETER_DATA_MODE` = D or A.
- `*_ADJUSTED_ERROR` must be surfaced for research use.

### 4.4 Intermediate Parameters

`TEMP_DOXY` = thermistor on optode, used to compute DOXY, not equivalent to CTD TEMP. Similarly `TEMP_PH`, `BPHASE_DOXY`, `C1PHASE_DOXY`, `FLUORESCENCE_CHLA` (raw counts), `BETA_BACKSCATTERING700` (raw) vs `BBP700` (derived). Intermediates should be hidden unless explicitly requested.

---

## 5. Index `parameters` Column Semantics

- **Definition:** Space-separated list of variables inside that specific NetCDF file (profile-level). One row = one file = one or more N_PROF profiles' union.
- **Bio index:** Always includes `PRES` + BGC + intermediates, never `TEMP/PSAL`. Proven: 0 exact TEMP in 401,749 rows.
- **Synthetic index:** Includes `PRES,TEMP,PSAL` + BGC, intermediates excluded. 395,089/395,090 rows have TEMP/PSAL exact.
- **Not float-level** (same WMO 6903091 shows 4 unique param sets across 430 cycles) nor mission-level.
- Reliability: reliable for file content, but requires **token-exact** matching, not substring. `str.contains("TEMP")` matches `TEMP_DOXY` → false positives 94% in Arabian Sea sample.

---

## 6. Regions

Current implementation: 13 bounding boxes + polygons, polygon authoritative after bbox.

Issues found:
- Pacific boxes cross dateline (`lon_min 100, lon_max -80`) impossible for `>= AND <=` filter → zero results.
- Ray-casting polygon does not handle antimeridian wrap.
- Arabian Sea polygon extends to 6N (Somali basin), true Arabian Sea >8-10N; Bay of Bengal extends to 2N (Malacca).
- Unknown region returns True (fail-open) → unfiltered query.
- Ocean code column `I/A/P` unused.

Recommendation: split dateline boxes, normalize longitude to 0-360 internally, source polygons from IHO/GEBCO, add missing subregions (Labrador, Arctic, OMZ), fail-closed on unknown.

---

## 7. Recommendations – Prioritized

**P0 Critical:**
- Dual-index loader: synthetic index for any query containing TEMP/PSAL or mixed core+BGC; bio index for pure BGC fast path.
- Fix parameter filter to token set membership, exclude intermediates via deny-list.
- Propagate alias map from reader to viz; viz must look for ADJUSTED columns.
- Update test fixtures: bio tokens must be `PRES TEMP_DOXY DOXY` not `PRES PSAL TEMP DOXY`.

**P1 Scientific correctness:**
- VariableRegistry from R03 vocab distinguishing core/BGC/intermediate, units, valid ranges, file types.
- QCFilter module, default QC 1,2,5,8, show error bars.
- Repository fetch S-file when needed; decode N_PROF>1 correctly.
- Fix region dateline handling, refine Arabian Sea / Bay polygons.

**P2 Robustness:**
- Parse index header correctly (skip comment lines, read header row), store GDAC update date, validate MD5.
- Surface `PARAMETER_DATA_MODE`, `DATA_MODE`, `DATE_UPDATE` in API.
- Group visualization by (float_id,cycle) not float_id alone to avoid mixing temporal profiles.

**P3 Enhancements:**
- Trajectory intent using `ar_index_global_traj`.
- IHO boundaries, citation DOI, DAC attribution.

---

## 8. References

- Argo User Manual v3.44, DOI 10.13155/29825, §4.1.2 B-Argo & Synthetic, §2.6 B-Argo features, §2.7 GDAC FTP directory format.
- GDAC docs: https://www.argodatamgt.org/Documentation
- Data FAQ B-files contain only BGC + PRES + intermediates, S-files contain TEMP/PRES/PSAL + BGC: https://argo.ucsd.edu/data/data-faq/
- Vocab R03: https://vocab.nerc.ac.uk/collection/R03/current/
- Argopy index spec: columns `file, date, latitude, longitude, ocean, profiler_type, institution, parameters, parameter_data_mode, date_update` for bio/synthetic.
