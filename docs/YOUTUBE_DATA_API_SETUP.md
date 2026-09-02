# YouTube Data API setup for Morning Intelligence

Morning Intelligence uses the official YouTube Data API as the primary acquisition path for `YouTube · Shorts Signals`.

## Why this is required

The legacy public Atom endpoints under `https://www.youtube.com/feeds/videos.xml` are retained only as a best-effort fallback. GitHub Actions live verification on 2026-09-02 showed all configured channel/feed variants returning HTTP 404 in the runner environment, so RSS cannot be treated as a reliable production dependency.

The collector therefore uses this order:

1. `YOUTUBE_API_KEY` present -> official YouTube Data API `playlistItems.list` against each channel's uploads playlist.
2. API unavailable/fails -> try the public Atom feed variants as fallback.
3. Neither path works -> fail closed with explicit provider/source failure classes.

## GitHub Actions secret

Create a GitHub Actions repository secret named exactly:

`YOUTUBE_API_KEY`

Do not commit the key to the repository, JSON configuration, workflow YAML, logs, or artifacts.

The workflow already maps the secret only to the YouTube acquisition step:

```yaml
env:
  YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}
```

If the secret is absent, artifacts report:

`provider_state = MISSING_API_KEY`

## Google API requirements

Enable YouTube Data API v3 for the Google Cloud project associated with the key. Restrict the key to the YouTube Data API where practical.

The collector uses the official `playlistItems.list` endpoint for the channel uploads playlist. This is a low-quota read operation and avoids the expensive `search.list` path.

## Release behavior

The release gate requires all of the following from YouTube acquisition:

- at least 10 fresh selected videos,
- at least 4 unique configured channels,
- real `youtube.com/watch?v=...` source URLs,
- real YouTube thumbnails,
- no synthetic/filler records.

A missing key does not silently pass. RSS fallback may satisfy the gate when it genuinely works, but if API and RSS are both unavailable the YouTube gate fails and the edition remains `INCOMPLETE`.

## Failure classes

Artifacts expose provider/source failures such as:

- `MISSING_API_KEY`
- `HTTP_403`
- `HTTP_404`
- `HTTP_429`
- `TIMEOUT`
- `NETWORK`
- `XML_PARSE`
- `JSON_PARSE`
- `EMPTY_FEED`
- `EMPTY_API_RESULT`

This separation is intentional: credential/configuration failures, provider availability failures, rate limits, malformed responses, and empty datasets should not be treated as the same incident.
