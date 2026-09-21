import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Card, Empty, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { palette } from '@/lib/theme';
import type { Car } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

export default function GarageScreen() {
  const { api } = useAuth(); const [cars, setCars] = useState<Car[] | null>(null);
  useFocusEffect(useCallback(() => { api<{ cars: Car[] }>('/driver/garage').then(body => setCars(body.cars)).catch(() => setCars([])); }, [api]));
  if (!cars) return <Loading />;
  return <Screen><Hero eyebrow="Your vehicles" title="Garage" subtitle="The cars available when you register for a driver event." /><SectionTitle title="Your cars" action={<Pressable onPress={() => router.push('/car/new')}><Text style={styles.add}>+ Add car</Text></Pressable>} />{cars.length ? cars.map(car => <Pressable key={car.id} onPress={() => router.push(`/car/${car.id}`)}><Card style={styles.car}><View style={styles.avatar}><Text style={styles.avatarText}>{car.make.slice(0, 1)}{car.model.slice(0, 1)}</Text></View><View style={{ flex: 1 }}><Text style={ui.title}>{car.label}</Text><Text style={ui.body}>{car.color || 'Color not listed'}</Text></View><Text style={styles.arrow}>›</Text></Card></Pressable>) : <Empty title="No cars yet" detail="Add your first car to use it when registering for an event." />}</Screen>;
}
const styles = StyleSheet.create({ car: { flexDirection: 'row', alignItems: 'center', gap: 13 }, avatar: { width: 54, height: 54, borderRadius: 15, backgroundColor: palette.navy, alignItems: 'center', justifyContent: 'center' }, avatarText: { color: 'white', fontWeight: '900', fontSize: 16 }, add: { color: palette.orange, fontWeight: '900' }, arrow: { color: palette.orange, fontSize: 28 } });
