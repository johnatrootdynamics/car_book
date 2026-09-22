# Track Ops mobile

Expo SDK 57 application for iOS and Android. It uses the existing Track Ops accounts and data through `/api/v1/mobile`.

## Included in the first slice

- Unified driver/staff/vendor/admin sign-in
- Forced temporary-password replacement and secure refresh-token storage
- Driver dashboard, upcoming events, tickets, Wallet links, and garage
- Native driver community with connection-only feeds, photo posts, comments, requests, and live people search
- Role-aware track employee home and event schedule
- Continuous QR scanner with manual name/email/code lookup
- Same-track and confirmed-payment enforcement before admission
- Clear already-used ticket warning
- Native RFID tag ordering, payment, fulfillment, activation, and scanner pairing
- RFID entrance/exit monitoring with event, ticket, and inspection eligibility checks

## Run

```sh
npm install
npx expo start --dev-client
```

The production API defaults to `https://carbook.root-dynamics.com`. For a different environment:

```sh
EXPO_PUBLIC_API_URL=https://example.com npx expo start
```

### iPhone Simulator

Install Xcode from the Mac App Store and add an iOS Simulator runtime in Xcode. Then create and run the local development build:

```sh
npx expo run:ios
```

For an EAS-hosted simulator build, use:

```sh
npx eas-cli build --platform ios --profile development
```

## Build

The bundle identifiers are `com.rootdynamics.trackops`. Configure an Expo account, then run:

```sh
npx eas-cli build --platform all
```

Store signing, Apple/Google developer accounts, privacy disclosures, screenshots, and store listings are deployment credentials/content and are intentionally not committed.
