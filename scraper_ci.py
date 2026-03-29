# 2. AbonoTeatro
abono_by_sala: dict[str, set[tuple[str, str]]] = {}
for sala, url in ABONO_URLS.items():
    shows = fetch_abonoteatro_shows(url)
    abono_by_sala[sala] = shows
    print(f"Abono {sala}: {len(shows)}")

# 3. Kultur (WebKit)
for sala in KULTUR_EVENTS:
    try:
        fetch_and_write_kultur_cache(sala)
    except Exception as e:
        print(f"⚠️  Kultur {sala}: {e}")

# 4. Build & write
payload = build_payload(current, abono_by_sala)
write_html(payload)
write_schedule_json(payload)
