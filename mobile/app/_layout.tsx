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
          <Stack.Screen name="event/[id]/checkout" options={{ title: 'Driver ticket' }} />
          <Stack.Screen name="event/[id]/spectator-checkout" options={{ title: 'Spectator tickets' }} />
          <Stack.Screen name="event-tools/[id]/[action]" options={{ title: 'Event operations' }} />
          <Stack.Screen name="event-planning/new" options={{ title: 'Create event' }} />
          <Stack.Screen name="event-planning/rentals" options={{ title: 'Rental availability' }} />
          <Stack.Screen name="car/[id]" options={{ title: 'Garage' }} />
          <Stack.Screen name="rfid" options={{ title: 'RFID tags' }} />
          <Stack.Screen name="inspection/[id]" options={{ title: 'Vehicle inspection' }} />
          <Stack.Screen name="staff/people" options={{ title: 'People' }} />
          <Stack.Screen name="staff/driver/[id]" options={{ title: 'Driver profile' }} />
          <Stack.Screen name="staff/orders" options={{ title: 'Orders' }} />
          <Stack.Screen name="staff/order/[kind]/[id]" options={{ title: 'Order details' }} />
          <Stack.Screen name="staff/hardware" options={{ title: 'Scanners & cameras' }} />
          <Stack.Screen name="staff/settings" options={{ title: 'Track settings' }} />
          <Stack.Screen name="admin/rfid" options={{ title: 'RFID fulfillment' }} />
        </Stack>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
