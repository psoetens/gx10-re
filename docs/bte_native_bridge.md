# BOSS TONE EXCHANGE — embedded web app & native-host bridge

Reverse engineering of how `bosstoneexchange.com` (BTE) talks to a native
host application. BTE is a Backbone.js SPA **designed to be embedded in a
native app** (this is how BOSS TONE STUDIO / the Roland "Quattro" app shell
present it). When it detects a native host it routes patch downloads/uploads
over a JSON message bridge instead of browser file I/O. A third-party host
(e.g. gxnarly's `WKWebView`) can impersonate that host to receive `.tsl`
livesets directly.

Verified live 2026-05-30 (signed in with a Roland account) by driving Chrome
via the chrome-devtools MCP: list API, liveset routes, native-mode activation,
and a full download→import bridge round-trip reassembling real GX-10 (1- and
3-patch) and GX-100 (4-patch) livesets. The reassembled `.tsl` `paramSet`
blocks match `bts_livesets.md` byte-for-byte.

## 1. Site shape

- SPA host `bosstoneexchange.com`; patch data served from the Roland Cloud
  Platform API at **`rcpsvc.roland.com/btc/…`** (CloudFront + API Gateway +
  Express). CORS `access-control-allow-origin: *`.
- Auth is **token-based** (JWT): `POST rcpsvc.roland.com/btc/tokens/refresh`
  returns 401 when logged out, 201 when a session exists. The SPA's ajax layer
  attaches the bearer token; the browsing/list endpoints below are public.
- Sign-in page: `/signin/?next=<path>`. Account area under `/mypage/…`.

### 1.1 List API (`searchLivesets`)

```
GET https://rcpsvc.roland.com/btc/searchLivesets/
      ?keyword=&gear=<gear>&view=block&sort=-createDate&from=<1-based>&size=<n>&tag=
```

- `gear` ∈ `gx-10`, `gx-100`, `gt-1000`, … (full gear list from
  `GET /btc/system/gears`; tag list from `GET /btc/system/tags`).
- `sort=-createDate` works; `sort=-downloadCount` returned empty in testing —
  use `-createDate` / `-updateDate`.
- Response: `{ items: [...], livesetCount: <total> }` (recon counts: 245 GX-10,
  738 GX-100). Item schema:

```jsonc
{
  "livesetId": "b1f71b16-935a-4485-997c-07a0b295503b",  // identity
  "name": "AiZO",
  "gear": "gx-10",
  "creatorName": "Noto", "creatorId": "…", "creatorVerified": false,
  "tags": ["Guitar","Rock"],
  "description": "…",
  "imageUrl": "https://bosstoneexchange.com/.../-img.webp",  // or /_shared/images/liveset/<gear>_NN.png placeholder
  "youtubeUrl": "", "likeCount": 0, "downloadCount": 16,
  "status": "Publish",
  "createDate": "2026-05-27T23:05:12+09:00", "updateDate": "…",
  "downloadFileName": "AiZO.tsl"            // download is always .tsl, named by liveset
}
```

### 1.2 Liveset detail / download route

- Detail page: `GET /liveset/{livesetId}/` (SPA route; adds no data beyond the
  list item — title, description, image, creator, Download button).
- The Download control is a form: `<form method="get" action="/liveset/{id}/">`
  with hidden `<input name="id" value="{livesetId}">` and
  `<button class="p-liveset-action__download-btn|p-liveset-download__btn"
  data-event-label="{livesetId}">`. In a plain browser this downloads the
  `.tsl`; in native-host mode the submit is routed over the bridge (§3).

## 2. Native-host activation

`window.NativaAppController` (sic — Roland's spelling) constructor:

```js
function () {
  if (location.search.indexOf("isNativeApp") !== -1) this.isNativeApp = true;
  if (navigator.userAgent.indexOf("roland.quattro") !== -1) this.isNativeApp = true;
  if (this.isNativeApp) { this.setBind(); this.setFileAcceptor(); this.setFileTransfer(); this.setOnSendMessageEvent(); }
}
```

So native mode turns on if **either** the page URL contains `isNativeApp`
**or** the User-Agent contains the token **`roland.quattro`**. Setting a
`WKWebView` `customUserAgent` containing `roland.quattro` activates it for the
whole session (verified `isNativeApp === true`).

## 3. The message bridge

Bidirectional JSON `{cmd, arg}` channel.

### 3.1 Transport (`sendMsgToBTS`)

```js
sendMsgToBTS(json) {
  if (UA.includes("Win"))     return chrome.webview.postMessage(json);     // Windows WebView2
  if (UA.includes("Android")) return bts.sendMsgToBTS(json);               // Android JS interface
  /* else (Mac/iOS) */        return webkit.messageHandlers.sendMsgToBTS.postMessage(json); // WKWebView
}
```

- **web → native:** host registers a `WKScriptMessageHandler` named
  **`sendMsgToBTS`**. The Mac branch (`else`) covers both macOS and iOS WKWebView
  (iOS UA contains neither `Win` nor `Android`).
- **native → web:** host calls **`window.onSendMsgToBTX(jsonString)`** via
  `evaluateJavaScript`.

### 3.2 Command dispatch (native → web, handled by `onSendMsgToBTX`)

| inbound `cmd`                     | handler                      | effect / reply |
|-----------------------------------|------------------------------|----------------|
| `requestEvaluateSignInSession`    | `doCheckSignInBTX`           | reply `responseEvaluateSignInSession {result:"signedIn"|"signedOut"}` (uses `BTX.authMng.isSignin()`) |
| `requestMoveToUploadPage`         | `doMoveToUploadPage`         | router → `/mypage/livesets/new/?mode=librarianExport` |
| `requestCheckRegionIsChina`       | `doCheckRegionIsChina`       | reply `responseCheckRegionIsChina {result}` |
| `responseGetTslFileInfo`          | `doGetTslFileInfo`           | upload path: `viewClass.setGearValue(arg.model)`; `fileAcceptor.startFileAccept(arg.tslFileName, arg.packetNum)` |
| `responseGetTslFileData`          | `doGetTslFileData`           | upload path: resolves next accept packet |
| `requestGetDownloadedTslFileData` | `doGetDownloadedTslFileData` | **download path**: reply `responseGetDownloadedTslFileData {packetNo, packetData}` |
| `resultImportToLibrarian`         | `doShowResultImportToLibrarian` | shows a BTE dialog `{title:result, message:detail}` |

### 3.3 Commands emitted by the web app (web → native)

`requestImportToLibrarian {packetNum}`, `responseGetDownloadedTslFileData
{packetNo, packetData}`, `responseEvaluateSignInSession {result}`,
`responseCheckRegionIsChina {result}`, `requestGetTslFileInfo {}` (upload),
`requestGetTslFileData {packetNo}` (upload), `notifyPreparingUploadInBTXView
{}`, `resultExportToBTX {result, detail}`.

## 4. Download → import (the path we use)

`AppFileTransfer` packetizes the downloaded `.tsl` and pushes it to the host:

- `setFile(fileData, fileName)` then `startFileTransfer()`:
  `setPackets()` → `BTX.nativeAppController.execRequestImportToLibrarian({packetNum})`.
- `setPackets()`: `btoa(fileData)` → **base64url** (`+`→`-`, `/`→`_`, `=`
  stripped), split into **8192-char** packets.

Verified sequence (host = our app):

```
(optional, on load)  N→W  requestEvaluateSignInSession
                     W→N  responseEvaluateSignInSession {result:"signedIn"}

user clicks Download
                     W→N  requestImportToLibrarian {packetNum:K}
for n in 1..K:
                     N→W  requestGetDownloadedTslFileData {packetNo:n}
                     W→N  responseGetDownloadedTslFileData {packetNo:n, packetData:<b64url chunk>}
host: join packetData[1..K] in order → base64url→base64 (`-`→`+`,`_`→`/`, pad `=`) → atob → .tsl text
                     N→W  resultImportToLibrarian {result, detail}   // optional success dialog
```

Recon results:

| liveset | gear | packets | bytes | patches |
|---------|------|---------|-------|---------|
| `b1f71b16…` "AiZO" | GX-10 | 1 | 63 | 0 (empty liveset) |
| `0ffdfb8f…` "GX-10 Presets apr 15" | GX-10 | 13 | 73 887 | 3 (CLEAN +1OCT, MONY, MONY) |
| `9eb06b84…` (4-channel amp set) | GX-100 | 17 | 98 501 | 4 (CHORUS, X-OD, X-DISTORTION, METAL DS) |

Each patch's `paramSet` has 43 blocks — `User_patch%common` (129B),
`User_patch%led` (28B), `User_patch%assign(1..20)` (45B ea),
`User_patch%efct` (62B), `User_patch%fxItem(1..20)` (179B ea) = 4699B —
identical for both gears, matching `bts_livesets.md`. The `.tsl` `device`
field is `GX-10` / `GX-100`.

## 5. Upload / export (reverse path, not yet used)

`AppFileAcceptor` + `doMoveToUploadPage` + `requestGetTslFileInfo` /
`requestGetTslFileData` is BTE's host→web upload contract: the host navigates
BTE to the upload page, hands over a `.tsl` packet-by-packet (host answers
`requestGetTslFileData {packetNo}`), and BTE fires a `fileLoadCompleted`
`CustomEvent {detail:{tslFileData, tslFileName}}`. This is the basis for a
future "share my patch to BTE" feature.

## 6. Replicating the download without a native app

Driveable headless for capture/testing (this is how the table above was
produced): load `/liveset/{id}/?isNativeApp=1`, stub
`window.webkit.messageHandlers.sendMsgToBTS.postMessage` to collect messages,
click the Download button, read `requestImportToLibrarian.packetNum`, then call
`window.onSendMsgToBTX('{"cmd":"requestGetDownloadedTslFileData","arg":{"packetNo":n}}')`
for each `n`, collect the `responseGetDownloadedTslFileData` packets, and
base64url-decode the concatenation → the `.tsl`.

## 7. Implications

- A host app (gxnarly) integrates by: (1) `WKWebView` with UA containing
  `roland.quattro`; (2) a `sendMsgToBTS` message handler; (3) driving
  `onSendMsgToBTX`. No DOM scraping, no `fetch`/XHR interception, no static
  download links needed — the bridge is Roland's own production contract and is
  stable across BTE redesigns.
- Sign-in is detectable over the bridge (`requestEvaluateSignInSession`);
  persistence is whatever the `WKWebsiteDataStore` retains (token/cookie).
- Downloads are always `.tsl` (livesets, 1..N patches) — no `.btx` involved on
  this path, resolving the earlier `.btx` ambiguity in `bts_livesets.md §“External .btx”`.
