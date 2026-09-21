import { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Card, Empty, Hero, Loading, Screen, ui } from '@/components/ui';
import { palette } from '@/lib/theme';
import type { Car } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

export default function GarageScreen() {
  const { api } = useAuth(); const [cars, setCars] = useState<Car[] | null>(null);
  useEffect(() => { api<{ cars: Car[] }>('/driver/garage').then(body => setCars(body.cars)).catch(() => setCars([])); }, [api]);
  if (!cars) return <Loading />;
  return <Screen><Hero eyebrow="Your vehicles" title="Garage" subtitle="The cars available when you register for a driver event." />{cars.length ? cars.map(car => <Card key={car.id} style={styles.car}><View style={styles.avatar}><Text style={styles.avatarText}>{car.make.slice(0, 1)}{car.model.slice(0, 1)}</Text></View><View style={{ flex: 1 }}><Text style={ui.title}>{car.label}</Text><Text style={ui.body}>{car.color || 'Color not listed'}</Text></View></Card>) : <Empty title="No cars yet" detail="Add your first car on the Track Ops website. Native editing is next on the roadmap." />}</Screen>;
}
const styles = StyleSheet.create({ car: { flexDirection: 'row', alignItems: 'center', gap: 13 }, avatar: { width: 54, height: 54, borderRadius: 15, backgroundColor: palette.navy, alignItems: 'center', justifyContent: 'center' }, avatarText: { color: 'white', fontWeight: '900', fontSize: 16 } });
