# Research Report

Research ID: `RES-20260828T072709Z-47EFB0A1`

For a new integration, use the Responses API by default. OpenAI's current migration guide explicitly recommends it for new projects and says Chat Completions remains supported. Responses is especially appropriate for built-in tools, typed multi-step outputs, and API-managed state; an existing simple message flow can stay on Chat Completions while migration is staged.

Migration must update more than the endpoint: consume typed output Items, choose state handling, move Structured Outputs from `response_format` to `text.format`, update function-call and streaming handling, and validate storage/retention. The official data-control guide says Responses application state may be retained for at least 30 days under its default/store behavior, while approved Zero Data Retention forces `store=false`.
