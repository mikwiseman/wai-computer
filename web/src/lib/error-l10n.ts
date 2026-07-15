/**
 * Client-side localization for backend error messages.
 *
 * The API speaks English in its `detail` strings; RU users used to see raw
 * English exactly when something broke (audit root cause D). This maps the
 * known, frequent backend messages to Russian. Unknown messages pass through
 * untouched — no fallback that hides the real error.
 */

export type ErrorLocale = "en" | "ru";

const RU_ERRORS: Record<string, string> = {
  // http.ts client-level
  "Your session ended. Please sign in again.": "Сессия истекла. Войдите снова.",
  "Unexpected error": "Неожиданная ошибка",
  // not-found family
  "Recording not found": "Запись не найдена",
  "Item not found": "Материал не найден",
  "Folder not found": "Папка не найдена",
  "Person not found": "Человек не найден",
  "Entity not found": "Сущность не найдена",
  "Device not found": "Устройство не найдено",
  "Agent not found": "Агент не найден",
  "Action item not found": "Задача не найдена",
  "Proposal not found": "Предложение не найдено",
  "Shared note not found": "Общая запись не найдена",
  "Subscription not found": "Подписка не найдена",
  "User not found": "Пользователь не найден",
  "Not found": "Не найдено",
  // pipeline / service
  "Summary not generated": "Саммари ещё не создано",
  "Summary audio has not been created.": "Аудио-резюме ещё не создано.",
  "Unable to connect to AI service": "Не удалось подключиться к ИИ-сервису",
  "AI service rate limit exceeded. Please try again later.":
    "Превышен лимит запросов к ИИ-сервису. Попробуйте позже.",
  "AI service error. Please try again later.":
    "Ошибка ИИ-сервиса. Попробуйте позже.",
  "Too many requests. Please try again later.":
    "Слишком много запросов. Попробуйте позже.",
  // billing
  "Promo code not found": "Промокод не найден",
  "Promo code already exists": "Такой промокод уже существует",
  "Subscription plan missing": "Тарифный план не найден",
};

/** Translate a known backend error message; unknown messages pass through. */
export function localizeErrorMessage(message: string, locale: ErrorLocale): string {
  if (locale !== "ru") return message;
  return RU_ERRORS[message] ?? message;
}
