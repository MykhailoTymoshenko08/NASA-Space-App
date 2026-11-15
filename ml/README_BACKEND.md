# ML-сервіс FieldShift: інструкція для бекенду

Схема: **Frontend → Backend → ML-сервіс**. Фронт до ML напряму не ходить. ML-сервіс без стану: ви шлете поле, пріоритети й сценарій,
отримуєте повний аналіз. Нічого не зберігає, ні користувачів, ні сесій. Повний контракт: [`ml/docs/api_contract.md`](docs/api_contract.md).
Живі приклади відповідей: [`docs/examples/`](docs/examples/) (Айова, Полк) та (Канзас, Reno).

Бекенд уже підключений: `cd backend && make ml` запускає реальний ML для локального `make dev`,
а `make up` запускає PostGIS, ML та API разом. Бекенд зберігає асинхронні `/v1/analyses` jobs,
адаптує стратегії для наявного фронтенду й повертає оригінальну ML-відповідь у `result.ml_analysis`.
`options.horizon_years` (1..5, типово 3) тепер задає горизонт реального планувальника.
Докладніше: [`backend/README.md`](../backend/README.md#how-it-works).

## 1. Запуск

### Варіант А: зібрати з репозиторію (основний, без наших скриптів, будь-яка архітектура)
Модель лежить у `models/crop_model/`, попередньо пораховані округи й клімат у `deploy/data/` (6 МБ, **вони в git навмисно**).
Нічого готувати не треба: свіжий клон і одна команда.

```bash
git clone https://github.com/MykhailoTymoshenko08/NASA-Space-App && cd NASA-Space-App/ml
docker compose up --build               # PORT=9000 docker compose up --build  для іншого порту
# або з кореня монорепо: docker compose -f ml/docker-compose.yml up --build
curl localhost:8001/ml/health
```

Працює на Intel/AMD (amd64) і на Apple Silicon/ARM (arm64): `Dockerfile` не залежить від архітектури.
Розмір: ~565 МБ розпаковано (стиснуто ~130 МБ). Пам'ять: ~400 МБ у спокої, до ~470 МБ під 20 паралельними запитами.

### Варіант Б: готовий образ-архів (без збірки)
Михайло може дати `fieldshift-ml-0.2.0-amd64.tar.gz` або `fieldshift-ml-0.2.0-arm64.tar.gz` (~130 МБ кожен; у git їх немає):

```bash
docker load -i fieldshift-ml-0.2.0-amd64.tar.gz     # або -arm64 на Mac M1+
docker run -d --name fieldshift-ml -p 8001:8001 -e PORT=8001 fieldshift-ml:0.2.0
```

Багатоархітектурний образ у реєстр (для CI): `docker buildx build --platform linux/amd64,linux/arm64 -t <registry>/fieldshift-ml:0.2.0 --push .`
Сервіс слухає порт зі змінної `PORT` (за замовчуванням 8001).

Коли змінюються precomputed-дані чи файли Ліни, Михайло виконує `python scripts/11_prepare_deploy.py` і коммітить `deploy/data`.

### Варіант В: без Docker, для розробки з моком
`ML_MODE=mock` не потребує даних і повертає правдоподібні вигадані числа у форматі контракту:

```bash
cd ml && python -m venv .venv && .venv/bin/pip install -r requirements-service.txt
ML_MODE=mock .venv/bin/uvicorn ml_service.main:app --port 8001
```

`ML_MODE=real` (за замовчуванням) дає справжній аналіз; `/ml/health` показує поточний режим у полі `mode`.

## 2. Адреси

База: `http://<хост>:8001` (порт з `PORT`). Swagger: `/docs`.

| метод | шлях | що |
|---|---|---|
| GET | `/ml/health` | `{status, model_version, mode, coverage}` |
| GET | `/ml/v1/meta/crops` | культури: `crop`, `cdl_code`, `name_en`, `name_uk`, `type` |
| POST | `/ml/v1/analyze` | головний запит |

CORS відкритий, авторизації немає (сервіс має бути за вашим бекендом).

## 3. Мінімальний запит

Обов'язково лише три речі: `field.field_id`, `field.centroid` (або `field.geometry`) і `field.admin.state` (`IA`, `IL`, `NE`, `KS`).
Усе інше має значення за замовчуванням.

```bash
curl -s -X POST localhost:8001/ml/v1/analyze -H 'content-type: application/json' -d '{
  "field": {
    "field_id": "191825000314326",
    "centroid": {"lat": 41.7428, "lon": -93.8136},
    "admin": {"state": "IA"}
  }
}'
```

З усіма необов'язковими полями (слайдери, фермер, мова):

```bash
curl -s -X POST localhost:8001/ml/v1/analyze -H 'content-type: application/json' -d '{
  "request_id": "any-string-you-want-back",
  "field": {"field_id": "201825002747884", "centroid": {"lat": 37.922, "lon": -97.9544}, "area_ha": 61.9,
            "admin": {"country": "US", "state": "KS", "state_fips": "20", "county_fips": "20155"}},
  "priorities": {"water": 0.8, "soil_health": 0.6, "nitrogen": 0.5, "erosion": 0.4, "income": 0.7},
  "scenario": {"temp_delta_c": 3.0, "precip_change_pct": -30},
  "farmer_input": {"irrigated": null, "current_rotation": null, "excluded_crops": ["alfalfa"], "has_livestock": null},
  "options": {"n_strategies": 3, "language": "uk"}
}'
```

Межі: `priorities` 0..1 (за замовчуванням 0.5), `scenario.temp_delta_c` −2..+4, `scenario.precip_change_pct` −40..+20, `n_strategies` 1..5,
`language` `en` або `uk`. `farmer_input.current_rotation` це список slug-ів, наприклад `["corn","soybean"]` (перевизначає визначену сівозміну).

### field_id = CSBID, **рядок**
`field_id` це поле `CSBID` з USDA Crop Sequence Boundaries (15 цифр, наприклад `"191825000314326"`). Завжди передавайте **рядком**, а не числом:
у JSON-числі втрачається точність. Центроїд бекенд бере зі своєї геометрії.

### Демо-округи (все вже пораховано, відповідь ~0,7 с)
| округ | FIPS | штат | полів |
|---|---|---|---|
| Polk | **19153** | Iowa | 5 263 |
| Reno | **20155** | Kansas | 20 961 |

Усі їхні поля та полігони: `data/fields/demo_fields_for_gee.geojson` (`field_id` + геометрія WGS84, 26 224 поля, 27 МБ) і `.zip` для GEE.
Це зручний файл, щоб завантажити поля в вашу БД. Для двох округів рядки `field_id` збігаються з тими, що знає ML.

### Поле поза демо-округами
Сервіс порахує його «на льоту»: **обов'язково** надішліть `field.crop_history` (інакше 422), ґрунт він візьме з USDA, клімат з NASA POWER.
Перший запит по новій клітинці клімату може йти **4–8 с**, далі швидко (кеш). Штати лише IA, IL, NE, KS.

```json
"crop_history": [{"year": 2024, "crop": "corn", "cdl_code": 1}, {"year": 2025, "crop": "soybean", "cdl_code": 5}]
```
Краще надсилати 8 років (2018–2025) із `cdl_code`: тоді правильно розпізнаються пар (61) і подвійні посіви (26 тощо).

## 4. Що в відповіді і що показувати

| поле | що це |
|---|---|
| `status` | `ok` або `partial` (`partial`, коли бракує NDVI або SMAP, або ґрунт органічний; відсутній TWI це лише попередження в `warnings`). Це не помилка, аналіз повний |
| `detected_rotation` | поточна сівозміна з історії, `label` готовий для показу |
| `summary` | `headline` (одне речення), `overall_risk` (`low/medium/high`), 3 `key_numbers` |
| `vulnerability_timeline` | 12 місяців: `bare_soil`, `moisture_deficit`, `heat_stress`, `frost_risk`, `extreme_precip` (0..1) + `flags` |
| `strategies` | `[0]` це поточна, далі рівно `n_strategies` альтернатив за убуванням `scores.overall`. У кожній: `scores`, `delta_vs_current`, `metrics`, `why`, `evidence`, `benefits`, `risks`, `data_gaps`, `check_with_agronomist` |
| `crop_suitability` | рейтинг 8 культур: `fit_score`, `next_year_share`, `rank`, `blocked`, `block_reasons`, `explanation` |
| `sources` | джерела, що справді використані |

`farmer_input.irrigated`: якщо поле зрошується, передайте `true`. Для сухих полів (наприклад, захід Небраски) без цього рейтинг культур
застосовує половинний штраф за брак води, а в `data_gaps` з'являється питання «Якщо поле зрошується, вкажіть irrigated=true: рекомендація зміниться».

Дві речі, які легко сплутати:
* `scores.income` **не гроші**, це відносний індекс 0–100 (`score_notes.income`). Підписуйте його так.
* У `crop_suitability` два числа: `fit_score` (0–100) каже, наскільки **поле** підходить культурі без урахування торішньої, а
  `next_year_share` (%, разом 100 по незаблокованих) це порада на **наступний рік** з урахуванням попередника. Культура може
  мати високий `fit_score`, але малу частку (наприклад, соя після сої); пояснення простими словами лежить у `explanation`.

## 5. Помилки

Формат завжди однаковий: `{"error": {"code": "...", "message": "...", "details": {...}}}`.

| HTTP | `code` | коли | що робити |
|---|---|---|---|
| 422 | `INVALID_INPUT` | поганий запит: межі, геометрія, невідома культура; поле не з демо-округів і без `crop_history` | показати/виправити запит, повторювати марно. Деталі в `details.errors` |
| 404 | `OUT_OF_COVERAGE` | штат не з IA, IL, NE, KS | повідомити користувачу, що регіон не покритий |
| 503 | `DATA_UNAVAILABLE` | зовнішні дані недоступні: не вдалося завантажити клімат для клітинки або недоступний сервіс ґрунтів USDA | **повторити через ~1 хвилину** (`details.retry_after_s` = 60). Завантаження клімату триває у фоні, повтор зазвичай успішний. Не більше 3 спроб |
| 500 | `INTERNAL` | помилка сервісу | логувати `request_id`, повідомити Михайла |

Поле з демо-округу ніколи не дає 503, бо все пораховано заздалегідь.

## 6. Швидкість і таймаути

Поле з демо-округу: **~0,7 с**. Нове поле: 4–8 с вперше. Таймаут бекенду 30 с із контракту з запасом.
Запити можна слати паралельно, сервіс без стану.

## 7. Перевірка і тести

```bash
curl localhost:8001/ml/health          # {"status":"ok","model_version":"0.2.0",...,"mode":"real"}
.venv/bin/python -m pytest -q          # 129 тестів: контракт, помилки, швидкість, файли від Ліни
```

## 8. Що ще зміниться

Ліна дає NDVI, SMAP і DEM. Після того як Михайло прожене `scripts/10_ingest_lina.py`, у відповідях зникнуть відповідні `warnings`,
`status` стане `ok`, у `sources` з'являться `landsat_ndvi`, `smap`, `nasadem`. **Формат відповіді не зміниться**: нові поля лише додаються.
