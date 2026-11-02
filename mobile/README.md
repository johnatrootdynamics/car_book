# Track Ops mobile

Expo SDK 57 application for iOS and Android. It uses the existing Track Ops accounts and data through `/api/v1/mobile`.

## Included in the first slice

- Unified driver/staff/vendor/admin sign-in
- Forced temporary-password replacement and secure refresh-token storage
- Driver dashboard, upcoming events, tickets, Wallet links, and garage
- Native driver community with connection-only feeds, photo posts, comments, requests, and live people search
- Native Community reporting, blocking, text safety screening, and enterprise moderation workflow
- In-app account deletion for drivers, staff, vendors, and enterprise admins
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

## App Store configuration

Public review links are available at `/privacy`, `/terms`, `/community-guidelines`, and `/support`. Set `SUPPORT_EMAIL` on the server to the monitored support address shown on those pages.

Sign in with Apple account deletion revokes the provider token when these server values are configured:

```env
APPLE_SIGN_IN_CLIENT_ID=com.rootdynamics.trackops
APPLE_SIGN_IN_TEAM_ID=YOUR_TEAM_ID
APPLE_SIGN_IN_KEY_ID=YOUR_KEY_ID
APPLE_SIGN_IN_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
```

Run the App Review safety tests and native checks before uploading a release:

```sh
python -m unittest discover -s tests -p 'test_app_review_safety.py' -v
cd mobile
npx tsc --noEmit
npx expo export --platform ios
```
