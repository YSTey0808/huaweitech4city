-- 002_search_profiles.sql
-- search_profiles(search_term): find users to add as friends, by username
-- or email. SECURITY DEFINER because emails live in auth.users, which
-- clients cannot query. Username matches by substring (friendly); email must
-- match EXACTLY (case-insensitive) so users cannot enumerate other people's
-- emails by substring probing. The caller's own row is excluded — you can
-- never find (and so never add) yourself.

create or replace function public.search_profiles(search_term text)
returns setof public.profiles
language sql
stable
security definer
set search_path = public
as $$
  select p.*
  from public.profiles p
  where length(trim(search_term)) > 0
    and p.id <> auth.uid()
    and (
      p.username ilike '%' || trim(search_term) || '%'
      or exists (
        select 1
        from auth.users u
        where u.id = p.id
          and lower(u.email) = lower(trim(search_term))
      )
    )
  limit 20;
$$;

revoke all on function public.search_profiles(text) from public, anon;
grant execute on function public.search_profiles(text) to authenticated;
