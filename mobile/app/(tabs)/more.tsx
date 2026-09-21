import { SymbolView } from 'expo-symbols';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Card, Hero, Screen, SectionTitle, ui } from '@/components/ui';
import { palette } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

type Destination = {
  title: string;
  detail: string;
  path: string;
  symbol: string;
};

const driverTools: Destination[] = [
  { title: 'Community', detail: 'Friends, circles, posts, and shared runs', path: '/user/community', symbol: 'person.2.fill' },
  { title: 'Event tickets', detail: 'Shop driver and spectator admission', path: '/user/spectator/events', symbol: 'ticket.fill' },
  { title: 'Private rentals', detail: 'Find and manage private track days', path: '/user/private-rentals', symbol: 'calendar.badge.plus' },
  { title: 'RFID tags', detail: 'Order and manage vehicle tags', path: '/user/rfid-tags', symbol: 'wave.3.right' },
  { title: 'Driver profile', detail: 'Public profile, follows, and account details', path: '/user/profile', symbol: 'person.crop.circle' },
];

const staffDaily: Destination[] = [
  { title: 'People', detail: 'Driver history, notes, classes, and vendors', path: '/employee/drivers', symbol: 'person.2.fill' },
  { title: 'Orders', detail: 'Track purchases, tickets, and resends', path: '/employee/orders', symbol: 'list.bullet.rectangle' },
  { title: 'Live track', detail: 'Current sessions, run groups, and timing', path: '/employee/live-track', symbol: 'flag.checkered' },
  { title: 'RFID scanners', detail: 'Zones, readers, cameras, and activity', path: '/employee/scanners', symbol: 'sensor.tag.radiowaves.forward.fill' },
];

const staffOffice: Destination[] = [
  { title: 'Event planning', detail: 'Create events, schedules, pricing, and limits', path: '/employee/events', symbol: 'calendar' },
  { title: 'Private rentals', detail: 'Availability, slots, bookings, and pricing', path: '/employee/private-rentals', symbol: 'calendar.badge.clock' },
  { title: 'Track settings', detail: 'Payments, staff, waivers, email, and inspections', path: '/employee/settings', symbol: 'gearshape.fill' },
];

const vendorTools: Destination[] = [
  { title: 'Vendor dashboard', detail: 'Your paid events and admission tickets', path: '/vendor/dashboard', symbol: 'storefront.fill' },
  { title: 'Find events', detail: 'Purchase vendor admission for upcoming events', path: '/user/spectator/events', symbol: 'calendar' },
  { title: 'Business profile', detail: 'Logo, website, menu, and public details', path: '/vendor/profile', symbol: 'building.2.fill' },
];

const adminTools: Destination[] = [
  { title: 'Tracks & onboarding', detail: 'Create tracks and onboard office staff', path: '/admin/dashboard', symbol: 'map.fill' },
  { title: 'Accounts', detail: 'Manage every account and password reset', path: '/admin/accounts', symbol: 'person.3.fill' },
  { title: 'All orders', detail: 'Review commerce across the platform', path: '/admin/orders', symbol: 'list.bullet.rectangle' },
  { title: 'RFID fulfillment', detail: 'Products, orders, inventory, and shipping', path: '/admin/rfid-tag-orders', symbol: 'shippingbox.fill' },
  { title: 'Platform settings', detail: 'Enterprise payments, SMTP, wallet, and templates', path: '/admin/settings', symbol: 'gearshape.fill' },
];

export default function MoreScreen() {
  const { account, openPortal } = useAuth();
  const [opening, setOpening] = useState('');
  const [error, setError] = useState('');
  if (!account) return null;

  const open = async (destination: Destination) => {
    setOpening(destination.path);
    setError('');
    try {
      await openPortal(destination.path);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to open that tool.');
    } finally {
      setOpening('');
    }
  };

  let sections: { title: string; items: Destination[] }[];
  if (account.type === 'user') sections = [{ title: 'Driver tools', items: driverTools }];
  else if (account.type === 'vendor') sections = [{ title: 'Vendor tools', items: vendorTools }];
  else if (account.type === 'admin') sections = [{ title: 'Enterprise tools', items: adminTools }];
  else sections = [
    { title: 'Track operations', items: staffDaily },
    ...(account.role === 'office_staff' ? [{ title: 'Office management', items: staffOffice }] : []),
  ];

  return <Screen>
    <Hero eyebrow="TrackOps" title="More tools" subtitle="Open the complete toolset with your current account—no second sign-in." />
    {error ? <View style={styles.error}><Text style={styles.errorText}>{error}</Text></View> : null}
    {sections.map(section => <View key={section.title} style={styles.section}>
      <SectionTitle title={section.title} />
      <Card style={styles.list}>
        {section.items.map((item, index) => <Pressable key={item.path} disabled={!!opening} onPress={() => open(item)} style={({ pressed }) => [styles.row, index > 0 && styles.divider, pressed && styles.pressed]}>
          <View style={styles.icon}><SymbolView name={{ ios: item.symbol, android: item.symbol, web: item.symbol } as any} tintColor={palette.orange} size={22} /></View>
          <View style={styles.copy}><Text style={ui.title}>{item.title}</Text><Text style={ui.body}>{opening === item.path ? 'Opening securely…' : item.detail}</Text></View>
          <Text style={styles.arrow}>›</Text>
        </Pressable>)}
      </Card>
    </View>)}
    <Text style={styles.note}>These tools open in a secure in-app window and use the same permissions as the TrackOps website.</Text>
  </Screen>;
}

const styles = StyleSheet.create({
  section: { gap: 10 },
  list: { paddingVertical: 2, paddingHorizontal: 16 },
  row: { minHeight: 76, flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 },
  divider: { borderTopWidth: 1, borderTopColor: palette.line },
  pressed: { opacity: 0.6 },
  icon: { width: 43, height: 43, borderRadius: 13, backgroundColor: palette.orangeSoft, alignItems: 'center', justifyContent: 'center' },
  copy: { flex: 1, gap: 3 },
  arrow: { color: palette.orange, fontSize: 28 },
  error: { padding: 14, borderRadius: 14, backgroundColor: palette.redSoft },
  errorText: { color: palette.red, fontWeight: '800' },
  note: { color: palette.muted, fontSize: 12, lineHeight: 18, textAlign: 'center', paddingHorizontal: 16 },
});
