import { Redirect, Tabs } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import type { ColorValue } from 'react-native';
import { Loading } from '@/components/ui';
import { palette } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

const Icon = ({ name, color }: { name: string; color: ColorValue }) => <SymbolView name={{ ios: name, android: name, web: name } as any} tintColor={color} size={23} />;
export default function TabLayout() {
  const { account, loading } = useAuth(); if (loading) return <Loading />; if (!account) return <Redirect href="/login" />; if (account.must_change_password) return <Redirect href="/change-password" />;
  const driver = account.type === 'user'; const staff = account.type === 'employee';
  return <Tabs screenOptions={{ headerShown: false, tabBarActiveTintColor: palette.orange, tabBarInactiveTintColor: '#667085', tabBarStyle: { height: 84, paddingTop: 9, backgroundColor: 'white', borderTopColor: palette.line }, tabBarLabelStyle: { fontSize: 11, fontWeight: '700', paddingBottom: 7 } }}>
    <Tabs.Screen name="index" options={{ title: 'Home', tabBarIcon: ({ color }) => <Icon name="house.fill" color={color} /> }} />
    <Tabs.Screen name="events" options={{ title: 'Events', href: driver || staff ? undefined : null, tabBarIcon: ({ color }) => <Icon name="calendar" color={color} /> }} />
    <Tabs.Screen name="tickets" options={{ title: 'Tickets', href: driver ? undefined : null, tabBarIcon: ({ color }) => <Icon name="ticket.fill" color={color} /> }} />
    <Tabs.Screen name="garage" options={{ title: 'Garage', href: driver ? undefined : null, tabBarIcon: ({ color }) => <Icon name="car.fill" color={color} /> }} />
    <Tabs.Screen name="scanner" options={{ title: 'Scanner', href: staff ? undefined : null, tabBarIcon: ({ color }) => <Icon name="qrcode.viewfinder" color={color} /> }} />
    <Tabs.Screen name="profile" options={{ title: 'Profile', tabBarIcon: ({ color }) => <Icon name="person.crop.circle.fill" color={color} /> }} />
  </Tabs>;
}
