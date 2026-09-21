import { Redirect } from 'expo-router';
import { Loading } from '@/components/ui';
import { useAuth } from '@/providers/AuthProvider';

export default function Index() {
  const { account, loading } = useAuth();
  if (loading) return <Loading />;
  if (!account) return <Redirect href="/login" />;
  if (account.must_change_password) return <Redirect href="/change-password" />;
  return <Redirect href="/(tabs)" />;
}
