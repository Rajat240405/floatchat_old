# Argo Data Model

**Audience:** FloatChat engineers maintaining metadata, repository, reader, viz.  
**Companion docs:** `../scientific/argo_scientific_audit.md` (audit), `../investigations/temp_query_root_cause.md` (TEMP failure).

---

## 1. Overview

Argo float data at GDAC consists of four layers:

```
DAC (AOML, Coriolis...) → NetCDF files → GDAC ftp/http → Index files (csv.gz) → FloatChat
```

Layers:
- **Metadata:** Index files describing all profile files (location, time, params).
- **Repository:** `dac/<dac>/<wmo>/profiles/<file>.nc` actual NetCDF.
- **Logical profiles:** Core (CTD), BGC (bio), Synthetic (merged core+BGC).
- **Variables:** raw, QC, adjusted, error, profile QC.

---

## 2. Float and Profile Lifecycle

### 2.1 Float

- WMO ID 7 digits, e.g., 6903091.
- Deployment → cycle 0 (surface tech/config, may have test subsurface profile, short duration).
- Cycle N: park drift (~1000 dbar), descend to max (~2000 dbar), ascent with sampling, surface transmit via Argos/Iridium with JULD, LAT, LON, POSITION_QC, JULD_QC.
- Ends with battery depletion, grounding, biofouling.
- Metadata: `<wmo>_meta.nc` (sensor list, calibration equations, deployment info), `<wmo>_tech.nc` (engineering), `<wmo>_<R/D>traj.nc` (trajectory times, non-profile measurements).

### 2.2 Profile

- **Single cycle may contain multiple profiles:** If `VERTICAL_SAMPLING_SCHEME` differs per sensor (e.g., DOXY sampled at different pressures than CTD, near-surface high-res, bouncing shallow profiles). Then `N_PROF >1` in file.
- **Synthetic merging:** GDAC creates `SR/SD` by merging R/D + BR/BD for same cycle: collect all distinct valid pressures where QC ∈ {1,2,5,8} (good, probably good, changed, estimated), sort ascending, `N_PROF=1`, `N_PARAM` = core+ BGC param count, values aligned on this axis. Auxiliary `*_dPRES` indicates interpolation distance.
- **DATA_MODE per profile:** `R` real-time (<12h), `A` adjusted RT (auto using previous DM offset), `D` delayed-mode (expert, 12 months core, 5-6 cycles BGC). Stored in `DATA_MODE(N_PROF)` and `PARAMETER_DATA_MODE(N_PROF,N_PARAM)`.

```
Float
 └─ Cycle 0 (tech)
 └─ Cycle 1
     ├─ Profile (N_PROF=0) core: PRES,TEMP,PSAL
     ├─ Profile (N_PROF=1) BGC: PRES,DOXY,CHLA...
     └─ Synthetic: merged PRES,TEMP,PSAL,DOXY...
 └─ Cycle N ...
```

---

## 3. GDAC Directory and Index Organization

### 3.1 Directory

```
dac/
  aoml/13857/profiles/R13857_001.nc
  aoml/1902453/profiles/BD1902453_004.nc
  aoml/1902453/profiles/SD1902453_004.nc
  coriolis/6903091/profiles/BR6903091_001.nc
  coriolis/6903091/6903091_meta.nc
  ...
geo/
  indian/2023/07/01/...
latest_data/
  2023/07/...
```

- `dac/<dac>/<wmo>/profiles/<prefix><wmo>_<cycle>[D].nc` canonical.
- Mirrors: `https://data-argo.ifremer.fr` and `https://usgodae.org/pub/outgoing/argo/dac`.

### 3.2 Index Files

| Index file | Full name | Columns | What it indexes | Row example |
|---|---|---|---|---|
| `ar_index_global_prof.txt.gz` | Profile directory file | `file,date,lat,lon,ocean,profiler_type,institution,date_update` (8 cols) | Core R/D | `aoml/13857/profiles/R13857_001.nc,...` |
| `argo_bio-profile_index.txt.gz` | Bio-Profile directory file | `file,date,lat,lon,ocean,profiler_type,institution,parameters,parameter_data_mode,date_update` (10 cols) | BR/BD only | `aoml/1900722/profiles/BD1900722_001.nc, PRES TEMP_DOXY BPHASE_DOXY DOXY, RRRD` |
| `argo_synthetic-profile_index.txt.gz` | Synthetic-Profile directory file | same 10 cols | SR/SD merged | `aoml/1902453/profiles/SD1902453_004.nc, PRES TEMP PSAL DOXY CHLA...` |
| `ar_index_global_traj.txt.gz` | Trajectory index | `file,lat_max,lat_min,lon_max,lon_min,profiler_type,institution,parameters,date_update` | R/D traj |
| `ar_index_global_meta.txt.gz` | Metadata directory | `file,profiler_type,institution,date_update` | meta.nc |

- Header 8-9 lines starting `#`, format version 2.2.
- `parameters` is **per-file** space-separated list of variables in that NetCDF (proven by matching `PARAMETER` var internal). For bio index, list includes intermediates (`TEMP_DOXY`), never core TEMP/PSAL.
- `parameter_data_mode` aligned order to `parameters`, per-param mode `R/A/D`.
- `ocean` single letter code ref table 13 (A Atlantic, I Indian, P Pacific...).
- `date` = JULD YYYYMMDDHHMMSS, `date_update` last GDAC update.
- Compression gzip, MD5 sidecar `.md5`.

FloatChat loads bio index only (7.7 MB, ~400k rows). Should load synthetic as well (7.8 MB, ~395k rows) for TEMP/PSAL queries.

---

## 4. NetCDF File Model

### 4.1 Dimensions

Common:

```
STRING2=2, STRING4=4, STRING8=8, STRING16=16, STRING32=32,
STRING64=64, STRING256=256, DATE_TIME=14,
N_PROF = int, number profiles in file (1..n)
N_LEVELS = int, vertical levels per profile (max, FillValue padded)
N_PARAM = int, distinct parameters in file
N_CALIB = 1, N_HISTORY = UNLIMITED
```

B-file example `BD1902453_004.nc`: `N_PROF=2, N_PARAM=16, N_LEVELS=511`.

S-file example `SD1902453_004.nc`: `N_PROF=1, N_PARAM=10, N_LEVELS=...`.

### 4.2 Data Section Relationships

```
Global attributes: title, institution, source, history, references, Conventions=Argo-3.1 CF-1.6, featureType=trajectoryProfile

General info per file:
  PLATFORM_NUMBER, CYCLE_NUMBER, DIRECTION (A/D), DATA_CENTRE, DATE_CREATION, DATE_UPDATE, DATA_MODE

Per N_PROF:
  JULD, LATITUDE, LONGITUDE, POSITION_QC, POSITIONING_SYSTEM,
  PROFILE_<PARAM>_QC (global profile flag Table 2a),
  PARAMETER_DATA_MODE (char N_PROF,N_PARAM)

Per N_PROF,N_LEVELS:
  PRES, PRES_QC, PRES_ADJUSTED, PRES_ADJUSTED_QC, PRES_ADJUSTED_ERROR
  TEMP, TEMP_QC, TEMP_ADJUSTED, ...
  PSAL, ...
  DOXY, DOXY_QC, DOXY_ADJUSTED, ...
  CHLA, ...
  BBP700, ...
  TEMP_DOXY (intermediate), ...

N_PARAM mapping:
  PARAMETER(N_PROF,N_PARAM,STRING16) lists param names
  SCIENTIFIC_CALIB_* (N_PROF,N_CALIB,N_PARAM,STRING256) calibration info
```

For S-file merged, additional: `TEMP_dPRES, PSAL_dPRES, DOXY_dPRES` indicating distance from original sampling.

### 4.3 Variable Taxonomy

**Core:**
- `PRES` dbar, `TEMP` °C ITS-90, `PSAL` psu practical salinity, `CNDC` S/m conductivity (rarely requested).

**BGC Primary (category b):**
- `DOXY, DOXY2, DOXY3` micromol/kg dissolved oxygen
- `CHLA, CHLA_2` mg/m3 chlorophyll-a
- `BBP700, BBP532, BBP470, BBP700_2` m-1 particle backscattering
- `NITRATE` micromol/kg
- `PH_IN_SITU_TOTAL, PH_IN_SITU_FREE` dimensionless pH
- `DOWNWELLING_PAR` microMolQuanta/m2/sec
- `DOWN_IRRADIANCE380,412,490,443,555,670` W/m2/nm
- `UP_RADIANCE*`
- `CDOM` ppb coloured dissolved organic matter
- `CP660` m-1 beam attenuation, `TURBIDITY`, `BISULFIDE`, etc.

**Intermediate / diagnostic (category ib):**
- `TEMP_DOXY, TEMP_DOXY2, TEMP_PH, TEMP_NITRATE, TEMP_CPU_CHLA, PRES_DOXY, PHASE_DELAY_DOXY, C1PHASE_DOXY, C2PHASE_DOXY, BPHASE_DOXY, RPHASE_DOXY, TPHASE_DOXY, FLUORESCENCE_CHLA, BETA_BACKSCATTERING700, VRS_PH, MOLAR_DOXY, PPOX_DOXY, COUNT_DOXY, FREQUENCY_DOXY, UV_INTENSITY_NITRATE, RAW_DOWNWELLING_PAR..., RAW_DOWNWELLING_IRRADIANCE*_STD/MED, SIDE_SCATTERING_TURBIDITY, TRANSMITTANCE_PARTICLE_BEAM_ATTENUATION660...`

These should not satisfy core queries. Synthetic files ignore them (per manual).

---

## 5. QC, Adjusted, Error

### 5.1 Levels

Per measurement:
```
X, X_QC, X_ADJUSTED, X_ADJUSTED_QC, X_ADJUSTED_ERROR
```

Per profile:
```
PROFILE_X_QC: A=100% good, B=75-100, C=50-75, D=25-50, E=0-25, F=0% good
```

### 5.2 Flags Table 2

- `1` good, `2` probably good, `3` probably bad correctable (use ADJUSTED), `4` bad discard, `5` changed, `8` estimated, `9` missing FillValue, `0` no QC.
- For science: accept 1,2,5,8.

### 5.3 Data Modes

- `PARAMETER_DATA_MODE` per param: R=RT, A=adjusted RT (auto), D=delayed.
- Best practice: prefer D > A > R, and `*_ADJUSTED` when available and QC good.

---

## 6. Relationships Diagram (ASCII)

```
[User Query]
    |
    v
[Intent Parser] -> ParsedIntent(variables, region, year, float_id)
    |
    v
[MetadataService]
    |-- loads argo_bio-profile_index.txt.gz (BR/BD) 400k rows
    |-- loads argo_synthetic-profile_index.txt.gz (SR/SD) 395k rows (recommended)
    |-- filters lat/lon bbox + polygon + date + parameters (token-exact) + float_id + profile_number
    |-- returns List[MetadataRecord(file, date, lat, lon, ocean, institution, parameters, parameter_data_mode)]
    |
    v
[RepositoryService]
    |-- file string "aoml/1902453/profiles/SD1902453_004.nc"
    |-- constructs URL {gdac_base_url}/dac/{file}
    |-- HTTP GET streaming bytes
    |-- netCDF4.Dataset(memory=bytes) -> NetCDFDataset wrapper (keeps bytes alive)
    |
    v
[NetCDFReader]
    |-- inspects ds.variables keys
    |-- resolves alias: TEMP -> TEMP_ADJUSTED if present, but must not map TEMP_DOXY
    |-- extracts arrays (N_PROF,N_LEVELS) converting masked FillValue 99999 to NaN, char QC to str
    |-- builds tidy DataFrame rows (profile_idx, level_idx, PRES, TEMP, PSAL, DOXY..., QC...),
         drops NaN PRES
    |-- returns DataFrame + alias_report
    |
    v
[VisualizationEngine]
    |-- groups by (float_id, cycle) -> traces
    |-- x = variable (ADJUSTED preferred), y = PRES inverted (surface top)
    |-- marker opacity = QC mapping 1->1.0,2->0.8,3->0.4,4->0.2
    |-- returns Plotly JSON
    |
    v
[QueryEngine] orchestrates, augments DataFrame with source_file, latitude, float_id, dac
    |
    v
[ChatResponse] figure + data_summary + map_data (lat/lon markers)
```

---

## 7. File Type Decision Matrix

| User asks for | Correct index | Correct file type to fetch | Contains? |
|---|---|---|---|
| `DOXY, CHLA, BBP700, NITRATE...` only | bio index (or synthetic) | BR/BD or SR/SD both work, BD has intermediates | B-file: DOXY present, TEMP absent; S-file: both present |
| `TEMP, PSAL` only | synthetic or core | SR/SD or R/D (core). Bio returns 0 exact. | Bio: no TEMP; Synthetic: TEMP present |
| `TEMP + DOXY` mixed | synthetic | SR/SD only | Bio lacks TEMP; Core lacks DOXY; Synthetic has both |
| `TEMP_DOXY` explicitly (diagnostic) | bio | BR/BD only | Synthetic ignores intermediates, so bio needed |

FloatChat P0 fix: route based on this matrix.

---

## 8. Implementation Notes for FloatChat

- **Metadata:** Load both indexes at startup, keep DataFrames in RAM (~80 MB total). Parse header correctly (skip comment lines, do not use `names=` to avoid header becoming data row). Store `date_update` and validate freshness via HTTP HEAD or MD5.
- **Parameter filter:** Tokenize `parameters.split()`, use set operation `required.issubset(file_params)`. Deny-list intermediates when checking core vars.
- **Repository:** `fetch` should validate file prefix matches requested variable category; if mismatch, try sibling S-file (`BD1902453_004.nc -> SD1902453_004.nc` replace first char B→S).
- **Reader:** Must handle N_PROF>1 (e.g., BD1902453_004.nc N_PROF=2 with different N_PARAM per prof). Current flatten loop `for prof_idx in range(n_prof)` then inner levels works but PROFILE grouping for viz must be by `profile_idx` not float_id alone.
- **QC:** Extract both `_QC` and `_ADJUSTED_QC`, use adjusted QC when plotting adjusted var.
- **Map data:** Deduplicate by (float_id, cycle) not float_id alone to avoid dropping temporal sampling for trajectory.

---

## 9. References

- User Manual v3.44 §2.6 B-Argo additional features, §4.1 file naming, §2.7 directory format – https://archimer.ifremer.fr/doc/00187/29825/120885.pdf
- BGC synthetic profile processing DOI 10.13155/55637
- Data FAQ: https://argo.ucsd.edu/data/data-faq/ – B vs S distinction.
- Vocab R03: https://vocab.nerc.ac.uk/collection/R03/current/ – param codes, categories.
- GDAC indexes live: `https://data-argo.ifremer.fr/argo_bio-profile_index.txt.gz`, `argo_synthetic-profile_index.txt.gz`
