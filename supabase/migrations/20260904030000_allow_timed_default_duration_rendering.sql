create or replace function public.record_calendar_delivery_success(
  p_event_id uuid,
  p_target_key text,
  p_external_calendar_ref text,
  p_external_event_id text,
  p_canonical_hash text,
  p_provider_version text default null,
  p_rendering_mode text default null,
  p_synced_at timestamptz default now()
) returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_event_id is null or not exists (
    select 1 from public.household_events where id = p_event_id
  ) then
    raise exception 'record_calendar_delivery_success: unknown event';
  end if;
  if p_target_key is null or not exists (
    select 1 from public.calendar_targets where target_key = p_target_key and active
  ) then
    raise exception 'record_calendar_delivery_success: unknown or inactive target';
  end if;
  if p_external_calendar_ref is null or btrim(p_external_calendar_ref) = '' then
    raise exception 'record_calendar_delivery_success: external calendar reference is required';
  end if;
  if p_external_event_id is null or btrim(p_external_event_id) = '' then
    raise exception 'record_calendar_delivery_success: external event ID is required';
  end if;
  if p_canonical_hash is null or p_canonical_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'record_calendar_delivery_success: invalid canonical hash';
  end if;
  if p_rendering_mode is not null
     and p_rendering_mode not in (
       'true_all_day',
       'same_day_2359',
       'timed',
       'timed_default_60m'
     ) then
    raise exception 'record_calendar_delivery_success: invalid rendering mode';
  end if;

  insert into public.calendar_event_links(
    event_id,
    target_key,
    external_calendar_ref,
    external_event_id,
    canonical_hash,
    provider_version,
    sync_state,
    last_synced_at,
    last_error,
    metadata
  )
  values (
    p_event_id,
    p_target_key,
    p_external_calendar_ref,
    p_external_event_id,
    p_canonical_hash,
    p_provider_version,
    'synced',
    coalesce(p_synced_at, now()),
    null,
    jsonb_strip_nulls(jsonb_build_object(
      'rendering_mode', p_rendering_mode,
      'sync_worker', 'calendar-reconciler-v1'
    ))
  )
  on conflict (event_id, target_key) do update set
    external_calendar_ref = excluded.external_calendar_ref,
    external_event_id = excluded.external_event_id,
    canonical_hash = excluded.canonical_hash,
    provider_version = excluded.provider_version,
    sync_state = 'synced',
    last_synced_at = excluded.last_synced_at,
    last_error = null,
    metadata = public.calendar_event_links.metadata || excluded.metadata,
    updated_at = now();
end;
$$;

revoke all on function public.record_calendar_delivery_success(
  uuid, text, text, text, text, text, text, timestamptz
) from public, anon, authenticated;

grant execute on function public.record_calendar_delivery_success(
  uuid, text, text, text, text, text, text, timestamptz
) to service_role;
