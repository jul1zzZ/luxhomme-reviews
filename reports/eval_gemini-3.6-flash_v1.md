# Проверка разметки: `gemini-3.6-flash|v1`

Отзывов в эталоне: 48, размечено моделью: 48.

| Метрика | Значение |
|---|---|
| Жалобы (тема + негатив): точность | 97% |
| Жалобы (тема + негатив): полнота | 100% |
| Темы: точность / полнота / F1 | 94% / 99% / 97% |
| Тон по совпавшим темам | 99% |
| Общий тон отзыва | 96% |
| Цитаты, найденные в тексте | 100% |

## По темам

| Тема | Точность | Полнота | TP | FP | FN |
|---|---|---|---|---|---|
| performance | 91% | 100% | 20 | 2 | 0 |
| quality_build | 86% | 100% | 6 | 1 | 0 |
| noise | 100% | 100% | 8 | 0 | 0 |
| ease_of_use | 100% | 100% | 8 | 0 | 0 |
| app_connectivity | 100% | 100% | 6 | 0 | 0 |
| delivery | 100% | 100% | 10 | 0 | 0 |
| packaging | 75% | 100% | 3 | 1 | 0 |
| price_value | 100% | 100% | 4 | 0 | 0 |
| support | 100% | 100% | 3 | 0 | 0 |
| design | 100% | 100% | 3 | 0 | 0 |
| general | 93% | 93% | 14 | 1 | 1 |

## Ошибки общего тона (эталон → модель)

- negative → mixed: 2

## Расхождения

| id | Отзыв | Эталон | Модель |
|---|---|---|---|
| r005 | Убирает нормально, но очень громкий, ночью не запустишь | negative; noise:-, performance:0 | mixed; noise:-, performance:0 |
| r016 | Пришёл с трещиной на корпусе, коробка целая. Брак | negative; quality_build:- | negative; packaging:+, quality_build:- |
| r017 | За свои деньги отличный пылесос, дешевле аналогов | positive; general:+, price_value:+ | positive; price_value:+ |
| r020 | Покрытие корзины отличное, ничего не пригорает, отмывается за минуту | positive; ease_of_use:+, quality_build:+ | positive; ease_of_use:+, performance:+, quality_build:+ |
| r036 | Доставка 10 дней, упаковка порвана, хорошо хоть сам гриль целый | negative; delivery:-, packaging:- | mixed; delivery:-, packaging:-, quality_build:+ |
| r043 | Отключается не докипятив. Брак | negative; quality_build:- | negative; performance:-, quality_build:- |
| r046 | Доставка ужасная, 11 дней. Сама машина ок | mixed; delivery:-, general:+ | mixed; delivery:-, general:0 |
| r048 | Купил вторым в дом, цена супер по скидке | positive; price_value:+ | positive; general:+, price_value:+ |
