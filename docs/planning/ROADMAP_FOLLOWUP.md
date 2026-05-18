Главные gaps, которые сейчас мешают росту:

Только два провайдера (один требует API-ключ).
Нет полностью локальных production-ready бэкендов без внешних зависимостей.
Ограниченная поддержка multi-agent sharing, causal/temporal памяти, concurrency.
Пока нет roadmap в открытом виде и примеров интеграции с популярными агентами.

Рекомендованный план развития AgentMemory (на ближайшие 1–3 месяца)

v0.2 (ближайший релиз)
Добавить MemPalace + улучшенный localjson/Memweave-style.
Полностью локальный режим по умолчанию (без API-ключей).
Расширить provider contract (добавить temporal/causal flags, multi-agent scoping).
Обновить README: большая таблица сравнения провайдеров + one-command демо.

v0.3
Интеграция Hindsight (MCP-native).
Улучшить concurrency и multi-process sharing.
Добавить больше примеров (OpenClaw, LangGraph, Cursor, Claude Code).

Маркетинг и рост (то, о чём мы говорили раньше)
Пост в r/AI_Agents и r/LLMDevs: «I built a shared memory runtime so agents finally stop forgetting between sessions — now with multiple backends».
Короткий тред на X с демо Browser UI + MCP в действии.
Создать Discord/Telegram для фидбека.
Добавить 4–5 good first issues (адаптер для нового провайдера, улучшение UI, тесты и т.д.).