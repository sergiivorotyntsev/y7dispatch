# Field Audit - y7dispatch CD API Integration

**Дата:** 2026-02-06
**Версия:** 1.0

---

## 1. СПРАВОЧНИКИ (Reference Data)

### 1.1 Auction Types (Типы аукционов)
| Код | Название | Location Type (авто) |
|-----|----------|---------------------|
| COPART | Copart | AUCTION |
| IAA | Insurance Auto Auctions | AUCTION |
| MANHEIM | Manheim | AUCTION |

### 1.2 Location Types (Типы локаций CD API)
| Значение | Описание | Когда использовать |
|----------|----------|-------------------|
| AUCTION | Аукцион | Pickup: COPART, IAA, MANHEIM |
| CROSS_DOCK | Кросс-док склад | Delivery: промежуточный склад |
| BUSINESS | Бизнес адрес | Delivery: офис/склад компании |
| RESIDENCE | Жилой адрес | Delivery: дом |
| PORT | Порт | Delivery: морской порт |

### 1.3 Brokers (Брокеры/Заказчики)
| ID | Код | Название | Описание |
|----|-----|----------|----------|
| 1 | TRT | TRT Logistics | Брокер с складами в TX, GA, CA |
| 2 | DAYTONACARGO | Daytona Cargo | Брокер с складами во FL |

### 1.4 Warehouses (Склады)
| Поле | Тип | Описание |
|------|-----|----------|
| code | TEXT | Уникальный код склада |
| name | TEXT | Название склада |
| address | TEXT | Улица |
| city | TEXT | Город |
| state | TEXT | Штат (2 буквы) |
| zip_code | TEXT | ZIP код |
| location_type | ENUM | CROSS_DOCK, BUSINESS, etc. |
| broker_id | INT | FK к brokers (какой брокер владеет) |
| buyer_reference | TEXT | Buyer Reference Number для CD |
| hours_json | JSON | Часы работы (примечание) |
| contact_json | JSON | Контактная информация |

---

## 2. ПОЛЯ ДЛЯ ЭКСПОРТА В CENTRAL DISPATCH

### 2.1 Vehicle Information (Информация о ТС)

| Поле | CD API Field | Обязат. | Источник | Редактируемое | Предзаполнение |
|------|-------------|---------|----------|---------------|----------------|
| vehicle_vin | vehicles[0].vin | ДА | EXTRACTED | ДА | Из документа |
| vehicle_year | vehicles[0].year | ДА | EXTRACTED | ДА | Из документа |
| vehicle_make | vehicles[0].make | ДА | EXTRACTED | ДА | Из документа |
| vehicle_model | vehicles[0].model | ДА | EXTRACTED | ДА | Из документа |
| vehicle_color | vehicles[0].color | НЕТ | EXTRACTED | ДА | Из документа |
| vehicle_type | vehicles[0].vehicleType | ДА | CONSTANT | ДА | По умолчанию: SEDAN |
| vehicle_condition | vehicles[0].isOperable | ДА | CONSTANT | ДА | По умолчанию: OPERABLE |
| vehicle_lot | vehicles[0].lotNumber | НЕТ | EXTRACTED | ДА | Из документа |
| vehicle_additional_info | vehicles[0].additionalInfo | НЕТ | COMPUTED | ДА | gate_pass + notes |

### 2.2 Pickup Location (Место забора)

| Поле | CD API Field | Обязат. | Источник | Редактируемое | Предзаполнение |
|------|-------------|---------|----------|---------------|----------------|
| pickup_location_type | stops[0].locationType | ДА | AUTO | НЕТ | AUCTION (для Copart/IAA/Manheim) |
| pickup_name | stops[0].locationName | НЕТ | EXTRACTED | ДА | "Copart Las Vegas" |
| pickup_address | stops[0].address.street | ДА | EXTRACTED | ДА | Из документа |
| pickup_city | stops[0].address.city | ДА | EXTRACTED | ДА | Из документа |
| pickup_state | stops[0].address.state | ДА | EXTRACTED | ДА | Из документа |
| pickup_zip | stops[0].address.postalCode | ДА | EXTRACTED | ДА | Из документа |
| pickup_phone | stops[0].contact.phone | НЕТ | EXTRACTED | ДА | Из документа |
| pickup_contact | stops[0].contact.name | НЕТ | EXTRACTED | ДА | Из документа |
| pickup_buyer_number | stops[0].buyerNumber | НЕТ | EXTRACTED | ДА | buyer_id из документа |
| pickup_notes | stops[0].notes | НЕТ | USER_INPUT | ДА | Пусто |

### 2.3 Delivery Location (Место доставки)

| Поле | CD API Field | Обязат. | Источник | Редактируемое | Предзаполнение |
|------|-------------|---------|----------|---------------|----------------|
| delivery_location_type | stops[1].locationType | ДА | WAREHOUSE | НЕТ | Из справочника склада |
| delivery_name | stops[1].locationName | НЕТ | WAREHOUSE | НЕТ | Из справочника склада |
| delivery_address | stops[1].address.street | ДА | WAREHOUSE | НЕТ | Из справочника склада |
| delivery_city | stops[1].address.city | ДА | WAREHOUSE | НЕТ | Из справочника склада |
| delivery_state | stops[1].address.state | ДА | WAREHOUSE | НЕТ | Из справочника склада |
| delivery_zip | stops[1].address.postalCode | ДА | WAREHOUSE | НЕТ | Из справочника склада |
| delivery_phone | stops[1].contact.phone | НЕТ | WAREHOUSE | НЕТ | Из справочника склада |
| delivery_contact | stops[1].contact.name | НЕТ | WAREHOUSE | НЕТ | Из справочника склада |
| delivery_buyer_number | stops[1].buyerNumber | НЕТ | WAREHOUSE | НЕТ | buyer_reference из склада |
| delivery_notes | stops[1].notes | НЕТ | USER_INPUT | ДА | Пусто |

### 2.4 Pricing (Ценообразование)

| Поле | CD API Field | Обязат. | Источник | Редактируемое | Предзаполнение |
|------|-------------|---------|----------|---------------|----------------|
| price_total | price.total | НЕТ | USER_INPUT | ДА | Пусто, требует ввода |
| price_cod_amount | price.cod.amount | НЕТ | USER_INPUT | ДА | Пусто |
| price_cod_method | price.cod.paymentMethod | НЕТ | CONSTANT | ДА | По умолчанию: CASH |
| balance_payment_method | balance.balancePaymentMethod | НЕТ | CONSTANT | ДА | CERTIFIED_FUNDS |
| balance_payment_time | balance.paymentTime | НЕТ | CONSTANT | ДА | 2_BUSINESS_DAYS_QUICK_PAY |
| balance_terms_begin_on | balance.balancePaymentTermsBeginOn | НЕТ | CONSTANT | ДА | RECEIVING_SIGNED_BOL |

### 2.5 Transport (Транспортировка)

| Поле | CD API Field | Обязат. | Источник | Редактируемое | Предзаполнение |
|------|-------------|---------|----------|---------------|----------------|
| trailer_type | trailerType | ДА | CONSTANT | ДА | По умолчанию: OPEN |
| available_date | availableDate | ДА | CONSTANT | ДА | Сегодня |
| expiration_date | expirationDate | НЕТ | USER_INPUT | ДА | +7 дней |

---

## 3. ВНУТРЕННИЕ ПОЛЯ (не экспортируются в CD)

| Поле | Источник | Описание |
|------|----------|----------|
| buyer_id | EXTRACTED | ID покупателя из документа |
| buyer_name | EXTRACTED | Имя покупателя |
| seller_name | EXTRACTED | Имя продавца |
| sale_date | EXTRACTED | Дата продажи на аукционе |
| total_amount | EXTRACTED | Сумма покупки |
| stock_number | EXTRACTED | Stock/Lot номер |
| gate_pass | EXTRACTED | Номер gate pass |
| order_id | GENERATED | Наш внутренний Order ID |
| warehouse_id | USER_INPUT | ID выбранного склада |

---

## 4. ВЫЯВЛЕННЫЕ ПРОБЛЕМЫ И ВОПРОСЫ

### 4.1 КРИТИЧЕСКИЕ ПРОБЛЕМЫ

#### P1: pickup_zip валидация падает
**Причина:** ZIP код может конвертироваться в integer (01234 → 1234), теряя ведущий ноль.
**Решение:** Нормализация ZIP перед валидацией, хранение как TEXT.

#### P2: Location Type не выбирается автоматически
**Текущее:** Ручной выбор.
**Требуется:** Для COPART/IAA/MANHEIM pickup_location_type = AUCTION автоматически.

#### P3: Price не редактируется в Documents list
**Причина:** Проверка `extraction` не проходит или поле заблокировано.
**Решение:** Проверить условие блокировки в Documents.jsx.

### 4.2 ВОПРОСЫ ДЛЯ УТОЧНЕНИЯ

1. **Buyer Reference Number** - откуда брать значение?
   - Из buyer_id в документе?
   - Из справочника Customer?
   - Из warehouse.buyer_reference?

2. **Operating Hours** - это:
   - Отдельное поле в UI?
   - Примечание в справочнике склада?
   - Не нужно отображать?

3. **Customer vs Broker** - в чём разница?
   - Broker = компания-перевозчик?
   - Customer = заказчик доставки?
   - Оба = один справочник или разные?

4. **Склад → Брокер связь:**
   - Один склад = один брокер?
   - Или один склад доступен нескольким брокерам?

---

## 5. ПРИОРИТЕТ ЗАПОЛНЕНИЯ ПОЛЕЙ

```
1. USER_OVERRIDE    → Ручные правки в Review UI (высший приоритет)
2. WAREHOUSE_CONST  → Константы из справочника склада
3. AUCTION_CONST    → Константы профиля аукциона
4. EXTRACTED        → Извлечено из документа
5. DEFAULT          → Значения по умолчанию (низший приоритет)
```

---

## 6. CD API ENUM VALUES

### trailerType
- OPEN
- ENCLOSED
- DRIVEAWAY

### locationType
- AUCTION
- BUSINESS
- RESIDENCE
- CROSS_DOCK
- PORT

### balancePaymentMethod
- CASH
- CHECK
- CERTIFIED_FUNDS
- COMCHECK
- ACH
- CREDIT_CARD
- ZELLE

### paymentTime
- IMMEDIATELY
- 1_BUSINESS_DAY
- 2_BUSINESS_DAYS_QUICK_PAY
- 5_BUSINESS_DAYS
- 15_BUSINESS_DAYS
- 30_BUSINESS_DAYS

### balancePaymentTermsBeginOn
- RECEIVING_SIGNED_BOL
- PICKUP
- DELIVERY

### vehicleType
- SEDAN
- SUV
- TRUCK
- VAN
- MOTORCYCLE
- BOAT
- RV
- ATV
- TRAILER
- OTHER

---

*Документ создан для аудита полей и выявления несоответствий.*
