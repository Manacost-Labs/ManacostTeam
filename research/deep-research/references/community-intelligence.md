# Community Intelligence

## Boundary

Reddit, X, YouTube, forums, reviews, and chat communities are useful for discovering practices, edge cases, language, hypotheses, and expert reasoning. They are not automatically representative samples.

Never write “Reddit thinks X” from one thread or “the community agrees” from high engagement.

## Collection

For every material community item, record:

- platform, URL, author/channel, date, and relevant version;
- thread or video context;
- claim and reasoning, not only conclusion;
- expertise signal when observable;
- whether the mention is independent or reacting to the same upstream event;
- supporting examples and counterarguments;
- engagement only as context, never as proof of truth or prevalence.

Use built-in ChatGPT Search/Web to locate and open the actual post, thread, or video page. When available, use the read-only RedditAPI and GetXAPI routes defined in [optional source providers](source-providers.md) to obtain direct Reddit/X records, timestamps, context, and visible engagement without flattening the platforms together. For YouTube, optional TranscriptAPI search can discover candidates and its transcript route can provide stable segment timestamps. If it is unavailable, use the explicitly labeled public-caption reserve route described in the provider contract. Inspect the video page and relevant segment before relying on it; if access is partial or captions are automatic/absent, label it.

Provider ranking is not community prevalence. Segment automated posts, giveaways, stickied material, crossposts, replies, and incomplete comment trees before interpreting a sample. Preserve the exact subreddit or X query, time window, sort/product, cursor, provider position, and collection time.

For a strategy guide, X and YouTube are section-level evidence channels rather than a single generic community pass. When provider access is available and the user has not set a tighter cost limit, give both channels `high` emphasis: search each decision-relevant guide section through several materially different angles, compare independent qualified creators, and preserve the reasoning or demonstration behind their conclusion. Abundant provider allowance does not justify bulk collection after saturation or weaken source checks.

For X, include the surrounding thread or replies when they qualify, correct, or challenge the post. For YouTube, attach the relevant timestamped segment to the guide section it informs; do not treat a title or full transcript as one undifferentiated evidence item. A transcript establishes what the speaker said, not whether the advice is correct or current.

## Expert detection for gaming and practitioner topics

Distinguish:

- casual user;
- high-rank or high-MMR player with verifiable current context;
- tournament player;
- content creator;
- developer or responsible official;
- theorycrafter or reproducible tester;
- statistical analyst or data provider.

Follower count is not sufficient expertise. Prefer current demonstrated performance, attributable professional role, methodological transparency, reproducible work, and topic-specific track record. A developer may be authoritative on mechanics but not necessarily optimal strategy; a top player may be authoritative on high-rank practice but not population-wide prevalence.

For YouTube, verify the player or coach independently before treating a channel as professional. A current tournament roster, official team/profile page, leaderboard identity, or linked verified account is stronger than a title containing “pro,” a large view count, or self-description. Record whether the video is a guide, tournament/VOD, coaching review, entertainment compilation, sponsored promotion, or reaction; these formats have different evidentiary weight.

Treat upload freshness and gameplay freshness as separate fields. A recent commentary upload may analyze an older match, pre-patch tournament, or replay. Verify the patch from the spoken context, visible client state, description, or an attributable recording date; otherwise lower freshness confidence.

## Synthesis categories

- `strong`: broad, repeated, independent cross-source agreement with little serious counterevidence;
- `moderate`: several independent sources converge, but coverage or representation is limited;
- `contested`: credible arguments or practice patterns exist on both sides;
- `weak`: sparse or dependent repetition;
- `anecdotal`: isolated observation that generates a hypothesis only.

Use “minority opinion” as a position label inside a contested or weak field, not as a precise population estimate unless sampling supports it.

## Analysis

Cluster posts by atomic community claim. Track platforms, independent mentions, expert support, counterarguments, and version. Explain likely reasons for disagreement, such as rank, patch, mode, skill, incentives, or visibility bias.

When community views differ from statistics, present both and investigate metric mismatch, lag, accessibility, conditional expertise, sampling, or survivorship. Do not optimize for agreement.

## Language

Prefer bounded formulations:

- “Among the discussions reviewed...”
- “Several independent high-rank sources...”
- “The accessible Reddit and YouTube sample leaned toward...”
- “This was an anecdotal signal, not measured prevalence.”

Report inaccessible or under-covered platforms as limitations.
