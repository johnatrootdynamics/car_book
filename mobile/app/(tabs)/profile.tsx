import { Redirect } from 'expo-router';

// Preserve legacy tab and deep links while every account type uses the same
// complete native security, privacy, support, and deletion screen.
export default function ProfileRedirect() {
  return <Redirect href="/account" />;
}
