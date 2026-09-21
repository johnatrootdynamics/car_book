import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AuthProvider } from '@/providers/AuthProvider';

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <StatusBar style="dark" />
        <Stack screenOptions={{ headerShadowVisible: false, headerBackTitle: 'Back' }}>
          <Stack.Screen name="index" options={{ headerShown: false }} />
          <Stack.Screen name="login" options={{ headerShown: false }} />
          <Stack.Screen name="change-password" options={{ headerShown: false }} />
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="event/[id]" options={{ title: 'Event details' }} />
          <Stack.Screen name="car/[id]" options={{ title: 'Garage' }} />
          <Stack.Screen name="inspection/[id]" options={{ title: 'Vehicle inspection' }} />
          <Stack.Screen name="staff/people" options={{ title: 'People' }} />
          <Stack.Screen name="staff/driver/[id]" options={{ title: 'Driver profile' }} />
          <Stack.Screen name="staff/orders" options={{ title: 'Orders' }} />
          <Stack.Screen name="staff/order/[kind]/[id]" options={{ title: 'Order details' }} />
          <Stack.Screen name="staff/hardware" options={{ title: 'Scanners & cameras' }} />
          <Stack.Screen name="staff/settings" options={{ title: 'Track settings' }} />
        </Stack>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
