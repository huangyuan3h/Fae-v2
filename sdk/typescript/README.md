# @fae/client

Thin TypeScript client for FAE Agent Core.

```ts
import { createClient } from "@fae/client";

const fae = createClient({
  baseUrl: "http://127.0.0.1:8000",
  token: process.env.FAE_CLIENT_TOKEN, // optional
});

const caps = await fae.getCapabilities();
await fae.chatStream(
  "hello",
  { apiKey: "" }, // server key default
  {
    onToken: (t) => process.stdout.write(t),
    onDone: () => {},
    onError: (c, m) => console.error(c, m),
  },
  "default",
);

fae.subscribeNotifications((title, body) => console.log(title, body));
```

Not published to npm in this slice — consume via workspace / `file:` dependency.
