import os
import json
import httpx
import asyncio
import logging
from openai import AsyncOpenAI
from datetime import datetime, timezone
logger = logging.getLogger(__name__)
async def search_jina_and_read(query: str, num_results: int = 3, content_length: int = 1500) -> dict:
    api_key = os.getenv("JINA_API_KEY")
    if not api_key:
        return {"status": "error", "message": "JINA_API_KEY not found in environment variables."}
    search_url = "https://s.jina.ai/"
    search_params = {"q": query}
    search_headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    urls_to_read = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            search_response = await client.get(search_url, headers=search_headers, params=search_params)
            search_response.raise_for_status()
            search_data = search_response.json()
            if not (search_data and search_data.get('data')):
                return {"status": "success", "data": "No search results found for the query."}
            for item in search_data['data'][:num_results]:
                if item.get('url'):
                    urls_to_read.append(item['url'])
    except httpx.RequestError as e:
        logger.warning("Jina search failed due to a network issue: %s. The agent will proceed without news.", e)
        return {"status": "success", "data": f"Skipping news search due to a network connection error: {e}"}
    except Exception as e:
        logger.error("Unexpected error during Jina search: %s", e, exc_info=True)
        return {"status": "error", "message": f"An unexpected error occurred during Jina search phase: {e}"}
    if not urls_to_read:
        return {"status": "success", "data": "Search successful, but no valid URLs were found to read."}
    async def _read_url(client, url: str) -> dict:
        reader_url = f"https://r.jina.ai/{url}"
        reader_headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        try:
            response = await client.get(reader_url, headers=reader_headers, timeout=40.0, follow_redirects=True)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning("Failed to read URL %s with Jina Reader: %s", url, e)
            return {"status": "error", "url": url, "message": str(e)}
    async with httpx.AsyncClient() as client:
        tasks = [_read_url(client, url) for url in urls_to_read]
        read_results = await asyncio.gather(*tasks)
    final_report = ""
    for result in read_results:
        if result.get("status") == "error" or "data" not in result:
            final_report += f"Error reading content from {result.get('url', 'N/A')}.\n\n"
        else:
            data = result['data']
            final_report += f"URL: {data.get('url', 'N/A')}\nTitle: {data.get('title', 'N/A')}\nContent: {data.get('content', 'No content available.')[:content_length]}...\n\n"
    return {"status": "success", "data": final_report.strip()}
def _is_event_today(event: dict, now_utc: datetime) -> bool:
    freq = event.get("frequency")
    day_of_week = event.get("day_of_week")
    is_weekday_match = False
    if day_of_week is not None:
        if isinstance(day_of_week, list):
            if now_utc.weekday() in day_of_week:
                is_weekday_match = True
        elif isinstance(day_of_week, int):
            if now_utc.weekday() == day_of_week:
                is_weekday_match = True
    if freq == "weekly" and is_weekday_match:
        return True
    elif freq == "monthly":
        day_range = event.get("day_of_month_range")
        week_of_month = event.get("week_of_month")
        if day_range and day_range[0] <= now_utc.day <= day_range[1]:
            return True
        elif week_of_month and is_weekday_match:
            first_day_of_month = now_utc.replace(day=1)
            first_weekday = first_day_of_month.weekday()
            day_offset = (day_of_week - first_weekday + 7) % 7
            target_day = 1 + day_offset + (week_of_month - 1) * 7
            if now_utc.day == target_day:
                return True
    elif freq == "quarterly":
        months = event.get("months", [])
        day_range = event.get("day_of_month_range", [])
        if now_utc.month in months and day_range and day_range[0] <= now_utc.day <= day_range[1]:
            return True
    elif freq == "scheduled" and now_utc.strftime("%Y-%m-%d") in event.get("specific_dates", []):
        return True
    return False
async def get_news_summary_for_cycle(model_config: dict, look_back_minutes: int = 120, look_forward_hours: int = 24, _test_now_utc: datetime = None) -> str:
    calendar_path = 'config/news_calendar.json'
    if not os.path.exists(calendar_path):
        logger.warning("News calendar file not found at %s. Skipping news check.", calendar_path)
        return ""
    try:
        with open(calendar_path, 'r', encoding='utf-8') as f:
            calendar_data = json.load(f)
        events = calendar_data.get("events", [])
    except (json.JSONDecodeError, IOError) as e:
        logger.error("Failed to load or parse news calendar: %s", e)
        return ""
    if _test_now_utc:
        now_utc = _test_now_utc
        logger.warning(f"!!! USING FAKE TIME FOR NEWS TEST: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')} !!!")
    else:
        now_utc = datetime.now(timezone.utc)
    events_in_window = []
    logger.debug(f"News Check: Current UTC time is {now_utc.strftime('%Y-%m-%d %H:%M:%S')}, weekday is {now_utc.weekday()}.")
    for event in events:
        event_name = event.get("event_name", "Unknown Event")
        if not _is_event_today(event, now_utc):
            logger.debug(f"Event '{event_name}' is not scheduled for today. Skipping.")
            continue
        event_time_str = event.get("time")
        if not event_time_str:
            logger.warning(f"Event '{event_name}' is for today but has no time specified. Skipping.")
            continue
        try:
            event_hour, event_minute = map(int, event_time_str.split(':'))
            event_time_today = now_utc.replace(hour=event_hour, minute=event_minute, second=0, microsecond=0)
            time_diff_minutes = (now_utc - event_time_today).total_seconds() / 60
            is_past_event = 0 <= time_diff_minutes < look_back_minutes
            is_future_event = - (look_forward_hours * 60) < time_diff_minutes < 0
            if is_past_event:
                logger.info(f"MATCH: Found past event '{event_name}' which occurred {time_diff_minutes:.1f} minutes ago.")
                events_in_window.append({"status": "past", "event": event, "time_diff_minutes": time_diff_minutes})
            elif is_future_event:
                logger.info(f"MATCH: Found upcoming event '{event_name}' scheduled in {-time_diff_minutes / 60:.1f} hours.")
                events_in_window.append({"status": "future", "event": event, "time_diff_minutes": time_diff_minutes})
            else:
                logger.debug(f"Event '{event_name}' is for today, but not in the time window (diff: {time_diff_minutes:.1f} mins).")
        except (ValueError, KeyError) as e:
            logger.warning("Skipping malformed event in news calendar: %s. Error: %s", event_name, e)
            continue
    if not events_in_window:
        logger.info("No major news events found in the relevant time window.")
        return "No high or medium importance news events detected recently or scheduled for today."
    past_events = [e for e in events_in_window if e['status'] == 'past' and e['event'].get('importance') in ['high', 'medium']]
    future_events = [e for e in events_in_window if e['status'] == 'future']
    final_summary_parts = []
    if past_events:
        all_articles = ""
        for item in past_events:
            event = item['event']
            logger.info("Processing recent event: %s. Fetching related news...", event['event_name'])
            for query in event.get("search_queries", []):
                search_result = await search_jina_and_read(query, num_results=2)
                if search_result.get("status") == "success":
                    all_articles += f"\n\n--- News related to '{event['event_name']}' ---\n{search_result.get('data', '')}"
        if all_articles.strip():
            try:
                api_key = os.getenv('TEMP_LLM_API_KEY')
                api_base = os.getenv('TEMP_LLM_API_BASE')
                if not api_key:
                    raise ValueError("Cannot summarize news: LLM API Key is not set.")
                client = AsyncOpenAI(api_key=api_key, base_url=api_base, max_retries=1, timeout=120)
                messages = [
                    {"role": "system", "content": "You are a financial analyst. Summarize the provided articles into a concise brief for an AI trader. Focus on factual data, market sentiment (dovish/hawkish), and immediate impact on major currency pairs and Gold. Must be under 300 words."},
                    {"role": "user", "content": f"Summarize news on recent events:\n\n{all_articles[:8000]}"}
                ]
                summary_response = await client.chat.completions.create(
                    model=model_config.get("model_id"),
                    messages=messages,
                    max_tokens=4096
                )
                summary_text = f"Recently Released News Summary:\n{summary_response.choices[0].message.content}"
                final_summary_parts.append(summary_text)
                logger.info("Successfully generated summary for past events.")
            except Exception as e:
                logger.critical("An error occurred during AI news summarization: %s", e, exc_info=True)
                final_summary_parts.append(f"Error summarizing news: {e}")
        else:
            logger.warning("Detected past event(s) but failed to fetch any news articles.")
    if future_events:
        future_events_str = "; ".join([f"{e['event']['event_name']} at {e['event']['time']} UTC" for e in sorted(future_events, key=lambda x: x['time_diff_minutes'])])
        final_summary_parts.append(f"Upcoming Events Today: {future_events_str}. Market may exhibit pre-event caution or volatility.")
    if not final_summary_parts:
        return "No high or medium importance news events detected recently or scheduled for today."
    final_output = "\n\n".join(final_summary_parts)
    cache_path = ".cache/latest_news.txt"
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'w', encoding='utf-8') as f:
        f.write(f"Generated at: {now_utc.isoformat()}\n\n{final_output}")
    return final_output