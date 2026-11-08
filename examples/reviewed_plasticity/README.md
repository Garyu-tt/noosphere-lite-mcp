# Reviewed graph plasticity — experimental reference

## Русский

**Это отдельный запускаемый пример механизма Noosphere R03/R04, а не обновление ядра Noosphere Lite MCP.** В Lite 0.3.x используется шифрованный NLV1-журнал и собственный граф заметок. Пример не модифицирует NLV1, не требует серверной базы и не включает автоматическое обучение через MCP без отдельного интегратора.

Зачем: если агент использовал **конкретную связь**, а **другой** проверяющий независимо воспроизвёл результат, её полезность должна измениться. Самооценка агента и лексическая похожесть не становятся обучающим сигналом.

Порядок работы:

1. Доверенный координатор регистрирует задание и исполнителя через begin_job. Пример принимает идентичности строками; **аутентификация выполняется внешним хостом**.
2. Исполнитель прикрепляет Edge(source, target, relation, layer, source_ref) и путь к доказательству относительно разрешённой папки через declare.
3. Независимый QA, отличный и от исполнителя, и от заказчика, из заранее заданного списка, утверждает usage_id и результат проверки через review.
4. cycle() проверяет SHA-256 и существование ребра в авторитетном графе, затем атомарно изменяет strength и utility. Повторы не удваивают награду.
5. weight() учитывает статус источника. Confidence отражает источник, но не автоматически повышается за успешные задачи. Можно откатить последнее событие через rollback.

Максимум четыре явно заявленные связи на задачу. Отказ снижает полезность. Никаких изменений весов GPT, нейронного fine-tuning или обещаний об автоматической научной достоверности.

**Приватность:** в отличие от NLV1, экспериментальный SQLite-sidecar **не шифруется**. Он хранит ID рёбер, заданий, относительные пути, SHA-256 и ревьюеров. Содержимое документов-доказательств не копируется. Используйте каталог с правами 0700 и шифрование файловой системы для чувствительных данных. Не сохраняйте эту базу в Git.

### Пример вызова

    from pathlib import Path
    from examples.reviewed_plasticity import Edge, ReviewedLearner

    graph = {Edge("note:1", "note:2", "supports")}
    artifacts = Path("/your/project/artifacts")
    private = Path("/your/private-state")  # already exists, chmod 0700
    learner = ReviewedLearner(
        private / "learning.sqlite3",
        artifacts,
        reviewers={"independent-qa"},
        has_edge=lambda edge: edge in graph,
    )

    # Authenticated integration host only. The evidence file must exist.
    learner.begin_job("job-001", requester="operator", assignee="worker")
    usage = learner.declare("job-001", "worker", next(iter(graph)), "test-result.json")
    learner.review("job-001", "independent-qa", True, [usage],
                   "Independently reproduced the test and checked edge attribution.")
    learner.cycle()
    print(learner.weight(next(iter(graph)), source_status="source_observation"))

Периодический cycle() следует запускать из **доверенного процесса**, не предоставляя этот интерфейс произвольным MCP-агентам.

Проверка:

    python3 -m unittest discover -s tests -p 'test_reviewed_plasticity.py' -v

## English

This is an **opt-in, runnable reference implementation** of Noosphere's R03/R04 reviewed graph learning. It is **not wired into Noosphere Lite MCP 0.3.x**, and it does not modify its encrypted journals or neural model weights.

A trusted host registers a task and authenticated principals. The worker attributes up to four exact graph edges and SHA-256-pinned project artifacts. A different allowlisted reviewer explicitly approves that attribution and independently examines the outcome. A periodic cycle revalidates evidence and edge membership and applies reversible, idempotent sparse weight updates. Confidence is derived from the source's epistemic status, not praise, usage frequency, or the agent's self-assessment.

**Security boundary:** This library does not implement principal authentication, network access control, or an independent test runner. Its caller MUST authenticate identities, enforce review authority, supply a trustworthy graph membership callback, and implement independently validated QA procedures. Do not expose these write methods directly as unrestricted MCP tools. A reviewer assertion alone is not objective proof.

**Privacy boundary:** The SQLite sidecar stores node IDs, task IDs, relative artifact paths and hashes, and reviewers **in plaintext**, unlike Lite's encrypted vault. Use a 0700 private parent directory and protect the filesystem. Never publish the database, journal, keys or evidence artifacts.

Test command is above. Only Python 3.11+ standard library is needed.
