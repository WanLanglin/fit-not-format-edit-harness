# Run logs

31 archives, one per batch, 5,642 runs: 4,746 valid runs of the first pass (the paper's "more than 4,700 runs"),
847 valid second runs and 49 invalid runs. The file format of a run is described in the top-level README.

## Invalid runs

A run is invalid when the provider or the harness fails rather than the model (`run.json`: `invalid_reasons`).
Every paired comparison uses the tasks with a valid run in every arm compared. A run that failed for such a reason
(no model output, an upstream error, a failed model call the harness did not abandon itself, or a turn cancelled
because its harness process stopped) was run again while its batch continued; each archive holds the last attempt
of every run. The proxy's running total in `model_calls.jsonl` (`ledger_total_usd`) also
counts the spend of the replaced attempts.

- In the verified-selection batches on the Aider refactors (`refactor-*-anchored`, `-aligned`, `-ref` and
  `-ref-rep1`), three tasks have no model call in any run:
  `common_methods_invocations_foreach_inputs_sample_func__sample_rightmost_arg`,
  `grpc_debug_server_EventListenerBaseServicer__process_tensor_event_in_chunks` and
  `introspection_DatabaseIntrospection__parse_column_or_constraint_definition`. Their run identifiers, which carry
  the longer arm name `lines_anchored`, exceeded the recording proxy's 128-character limit, so the proxy refused
  every request. The paired comparisons of Tables 2 and 3 therefore leave them out (84 tasks for GPT-5.6-luna and
  85 for MiMo-v2.5-Pro in the first run). `editbench/orproxy.py` now accepts identifiers of up to 255 characters.
- 12 runs ended when their batch reached the spending cap that the recording proxy enforces: the proxy answered
  `429` with `budget exhausted` (`model_calls.jsonl`), and `run.json` lists the run as an upstream failure at the
  proxy (10) or a ghost run (2). They are invalid and were not run again: 3 in `canitedit-claude-sonnet5-2arms`, 1 in
  `canitedit-claude-sonnet5-ref`, 7 in `refactor-luna-rep1` and 1 in `refactor-mimo-3arms`.
- A turn whose model stream stalls for 60 s ends there and is graded like any other run; the stall alone does not
  make it invalid.
  This happened in 18 MiMo-v2.5-Pro refactor runs: 13 in the baseline arms and 5 in the verified-selection arms.
