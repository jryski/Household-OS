create index if not exists calendar_delivery_rules_category_key_idx
  on public.calendar_delivery_rules(category_key);

create index if not exists household_event_categories_parent_key_idx
  on public.household_event_categories(parent_key);

create index if not exists household_event_evidence_source_id_idx
  on public.household_event_evidence(source_id);

create index if not exists household_events_source_agent_idx
  on public.household_events(source_agent);

create index if not exists household_events_supersedes_idx
  on public.household_events(supersedes);

create index if not exists household_ingest_sources_parser_agent_idx
  on public.household_ingest_sources(parser_agent);
