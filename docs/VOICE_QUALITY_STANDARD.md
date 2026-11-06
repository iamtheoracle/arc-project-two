# Oracle Arc natural-speech quality standard

## Product target

Oracle Arc speech should sound like a calm, clear, expressive human speaker rather than a navigation system. Naturalness is a release requirement, not a marketing adjective. A model is not approved merely because it returns a valid WAV file.

The system must preserve the written answer as the source of truth. Speech generation may add sentence-aware pauses and pronunciation handling, but must not paraphrase, omit, or invent content.

## Voice model selection

Evaluate candidate neural TTS models against the same fixed, versioned test corpus. Compare:
- Naturalness and prosody: sentence rhythm, phrase grouping, pauses, emphasis and non-monotonic intonation.
- Intelligibility: consonant clarity, vowel quality, word boundaries and performance at normal playback speed.
- Pronunciation: common names, acronyms, numbers, dates, currency, abbreviations and domain vocabulary.
- Language and accent: only claim locales that have passed the complete corpus and native-speaker review.
- Stability: repeatability, malformed-output rate, memory use, cold-start time and sustained throughput.
- Deployment: model license, redistribution terms, immutable revision, checksums, offline operation and CPU/GPU requirements.

Piper remains the initial local implementation. Some Piper voices can be clear and pleasant, but quality varies substantially by voice and training data. Do not label the default Piper voice near-human without listening-test evidence. Keep the runtime behind a provider-neutral synthesis interface so a higher-quality approved neural model can replace it without changing the public session API.

No voice model may be downloaded at request time. Provisioning must pin the immutable upstream revision and verify every model/config asset by SHA-256. License and provenance review is mandatory before model activation.

## Text preparation

Before synthesis, a deterministic text-normalization layer should:
- Expand dates, times, currencies, measurements and numbers using the requested locale.
- Preserve acronyms and product names using reviewed pronunciation lexicons.
- Split long responses into sentence-aware segments without changing wording or order.
- Avoid reading markdown syntax, URLs, code fences or decorative symbols aloud.
- Keep punctuation and paragraph boundaries as prosody hints.
- Reject unsupported language/voice combinations rather than silently switching accents.

Normalization must be reversible/auditable and tested against exact source text. Do not insert emotional claims, filler words or conversational paraphrases.

## Evaluation corpus and gates

Maintain a versioned corpus with at least:
- Short conversational responses, long explanations and multi-paragraph answers.
- Questions, lists, punctuation, quotations and sentence-final intonation.
- Numbers, dates, currency, units, URLs, email addresses and acronyms.
- Common Nigerian and international names, with reviewed pronunciation entries.
- Difficult consonant clusters, borrowed words and representative locale-specific vocabulary.
- Empty, whitespace-only, extremely long and adversarial markup inputs.

Every candidate must pass automated format/integrity checks and a blind listening review by multiple human evaluators. Record model revision, voice ID, configuration, hardware, synthesis duration, real-time factor, peak memory, failure rate and evaluation results.

Recommended minimum release gates:
- No clipped, truncated, corrupt or unintelligible outputs in the release corpus.
- 100% exact text coverage after deterministic normalization; no dropped or invented sentences.
- At least 4.0/5 mean naturalness and intelligibility ratings from blind human review, with no test category below 3.5/5.
- Median real-time factor at or below 0.5 on the declared reference hardware for standard responses; report p95 separately.
- Pronunciation lexicon regression tests pass for every supported locale.
- All security, isolation, provenance, cancellation and privacy tests pass.

These are proposed engineering gates; results must be measured and published before the model is called approved.

## Runtime experience

- Keep text visible while speech is prepared and provide a clear pending/ready/failed state.
- Start playback only after the full artifact or a validated stream segment is available.
- Provide pause, resume, stop and immediate interruption controls.
- A stopped or cancelled turn must never publish stale audio later.
- Respect system output volume and accessibility controls; never auto-play without an explicit user action.
- Do not store microphone input or generated audio by default.
- Never use voice cloning or infer a speaker's identity from audio.

## Honest product language

Use "local speech synthesis available" when the worker is configured and verified. Use "natural-sounding voice approved" only after the human evaluation gates pass. Use "near-human" only if comparative, blind listening evidence supports that specific claim. Otherwise describe the measured quality plainly.
