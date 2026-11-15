# Скрипти Google Earth Engine (Ліна)

Супутникові дані для ML-сервісу рахуються тут, у Google Colab, і потрапляють у сервіс через `scripts/10_ingest_lina.py`.
Скрипти Ліни, логіка не змінена. Ми лише додали обробку полів **пачками по 300** в `ndvi.py` і `smap_slope.py`
(Earth Engine віддає за один `ee_to_df` не більше 5 000 записів, а демо-полів 26 224). `smap_rootzone.py` вже працював пачками.
Скрипти ніколи не запускались у цьому репозиторії: перевірено лише синтаксис, а читання її файлів перевірено тестами на синтетичних файлах.

| скрипт | що робить | вихідні файли |
|---|---|---|
| `ndvi.py` | NDVI з Landsat HLS (`NASA/HLS/HLSL30/v002`, 30 м) для кожного поля й дня від 2015 року, відкидає хмари й сніг, потім місячне середнє для днів із хмарами в полігоні < 15% | `hls_ndvi_daily.csv`, `hls_ndvi_monthly_long.csv`, `hls_ndvi_monthly_wide.csv` |
| `smap_rootzone.py` | вологість кореневої зони SMAP L4 (`NASA/SMAP/SPL4SMGP/007`) у центроїді поля, місячні середні від квітня 2015 | `smap_monthly_long.csv`, `smap_monthly_wide.csv` |
| `smap_slope.py` | схил NASADEM (`NASA/NASADEM_HGT/001`, 30 м): медіана й 90-й перцентиль по полю | `terrain2.csv` |
| `slope_rules.py` | **лише документація** її правила: просапні культури (F = 0) на схилі p90 > 5°. Не запускається, логіка вже в `config/crop_rules.yaml` | `fields_filtered.csv` |

## Колонки

Скрипти, які ми використовуємо в сервісі (решта довідкові):

* `hls_ndvi_monthly_long.csv`: `field_id, date (YYYY-MM), year, month, ndvi_hls, n_obs`
* `smap_monthly_long.csv`: `field_id, date (YYYY-MM), year, month, smap_rootzone`
* `terrain2.csv`: `field_id, slope_deg, slope_deg_p90`

`scripts/10_ingest_lina.py` приймає ці назви напряму: `ndvi_hls` стає `ndvi_mean`, `date` відкидається, градуси переводяться у відсотки
`slope_pct = tan(radians(slope_deg)) × 100`. TWI у її файлах немає, правило вологих пониззь залишається вимкненим.

## Вхід: fields.geojson

Усі скрипти читають `fields.geojson` з колонкою **`field_id`** (це CSBID, рядок) і геометрією. `slope_rules.py` додатково `crop`. Два набори полів
(створює Михайло, у git їх немає, бо файли великі):

| набір | файл | полів | звідки |
|---|---|---|---|
| вибірка для навчання | `data/fields/fields_for_gee.geojson` (+ `.zip` шейпфайл) | 2 000 | `scripts/01_sample_csb.py` |
| демо-округи Polk і Reno | `data/fields/demo_fields_for_gee.geojson` (+ `.zip`) | 26 224 | `scripts/09b_export_demo_polygons.py` |

## Як запустити в Colab (двічі, по набору)

1. Завантажте `.py` у Colab (або вставте в комірки), покладіть набір полів поруч під назвою **`fields.geojson`**.
2. Для NDVI і SMAP запустіть `ndvi.py`, `smap_rootzone.py`, `smap_slope.py`; перед першим запуском вони самі викличуть `ee.Authenticate()`.
3. Для другого набору змініть **назви вихідних файлів**, щоб не затерти перший: `_sample` і `_demo` перед `.csv`
   (наприклад `OUT_LONG = 'hls_ndvi_monthly_long_demo.csv'`), або скачайте результати першого набору в окрему папку.
4. Скачайте результати в дві папки, наприклад `lina_sample/` і `lina_demo/`. Файли всередині мають свої оригінальні назви.

Орієнтовний час: `ndvi.py` і `smap_rootzone.py` на 26 тис. полів це довгі запуски (години), бо запити йдуть по місяцях і пачках. Якщо Earth Engine скаржиться
на 5 000 записів, `ndvi.py` сам ділить пачку навпіл. Якщо зависає, зменште `BATCH`.

## Як віддати файли сервісу

```bash
cd ml
python scripts/10_ingest_lina.py --incoming ~/Downloads/lina_sample --dry-run   # лише звіт: колонки, діапазони, невідомі field_id
python scripts/10_ingest_lina.py --incoming ~/Downloads/lina_sample             # перший набір
python scripts/10_ingest_lina.py --incoming ~/Downloads/lina_demo --merge       # другий набір ДОДАЄТЬСЯ до першого, не замінює
python scripts/11_prepare_deploy.py                                             # оновити deploy/data для образу
```

Скрипт відхиляє файл, де більше 5% рядків поганих (поза діапазоном, порожні, невідомі `field_id`). Після встановлення сервіс сам підхоплює файли:
з'являються джерела `landsat_ndvi`, `smap`, `nasadem`, зникають попередження про NDVI і SMAP. Статус лишається `partial`, доки немає TWI.

## Правило схилу з `slope_rules.py`

Для кожного поля `F = 0`, якщо культура просапна (кукурудза, соя, бавовник, сорго, цукрові буряки, картопля) і схил (p90) більший за 5°; `F = 1` для
озимої пшениці, люцерни, ячменю й вівса; невідома культура або немає схилу дають порожнє значення з причиною. У нашому сервісі ця ідея
стоїть у `config/crop_rules.yaml` як `steep_slope_row_crops` (поріг 5° = 8,7%), але порівнюється **медіанний** схил, а не p90, і це м'який штраф, а не жорсткий нуль.
Розбіжність помічена в `docs/algorithm.md`, розділ 14.3.
