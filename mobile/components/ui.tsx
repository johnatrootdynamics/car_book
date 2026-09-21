import { PropsWithChildren, ReactNode } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleProp, StyleSheet, Text, TextInput, TextInputProps, View, ViewStyle } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { palette, shadow } from '@/lib/theme';

export function Screen({ children, scroll = true }: PropsWithChildren<{ scroll?: boolean }>) {
  const content = scroll ? <ScrollView contentContainerStyle={styles.content}>{children}</ScrollView> : <View style={styles.content}>{children}</View>;
  return <SafeAreaView edges={['top']} style={styles.screen}>{content}</SafeAreaView>;
}

export function Hero({ eyebrow, title, subtitle }: { eyebrow?: string; title: string; subtitle?: string }) {
  return <View style={styles.hero}>
    {eyebrow ? <Text style={styles.eyebrow}>{eyebrow}</Text> : null}
    <Text style={styles.heroTitle}>{title}</Text>
    {subtitle ? <Text style={styles.heroSubtitle}>{subtitle}</Text> : null}
  </View>;
}

export function Card({ children, style }: PropsWithChildren<{ style?: StyleProp<ViewStyle> }>) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function Field(props: TextInputProps) {
  return <TextInput placeholderTextColor="#98A2B3" {...props} style={[styles.field, props.style]} />;
}

export function Button({ title, onPress, tone = 'primary', disabled = false }: { title: string; onPress: () => void; tone?: 'primary' | 'secondary' | 'danger'; disabled?: boolean }) {
  return <Pressable disabled={disabled} onPress={onPress} style={({ pressed }) => [styles.button, tone === 'secondary' && styles.secondaryButton, tone === 'danger' && styles.dangerButton, (pressed || disabled) && { opacity: .7 }]}>
    <Text style={[styles.buttonText, tone === 'secondary' && styles.secondaryButtonText]}>{title}</Text>
  </Pressable>;
}

export function SectionTitle({ title, action }: { title: string; action?: ReactNode }) {
  return <View style={styles.sectionTitle}><Text style={styles.sectionTitleText}>{title}</Text>{action}</View>;
}

export function Empty({ title, detail }: { title: string; detail: string }) {
  return <Card style={styles.empty}><Text style={styles.emptyTitle}>{title}</Text><Text style={styles.body}>{detail}</Text></Card>;
}

export function Loading() {
  return <View style={styles.loading}><ActivityIndicator color={palette.orange} size="large" /></View>;
}

export const ui = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center' },
  between: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { color: palette.ink, fontSize: 18, fontWeight: '800' },
  body: { color: palette.muted, fontSize: 14, lineHeight: 20 },
  label: { color: palette.ink, fontSize: 13, fontWeight: '700', marginBottom: 7 },
  pill: { backgroundColor: palette.orangeSoft, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 },
  pillText: { color: '#C2410C', fontSize: 12, fontWeight: '800' },
  gap: { gap: 12 },
});

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: palette.canvas },
  content: { flexGrow: 1, padding: 18, paddingBottom: 36, gap: 16 },
  hero: { backgroundColor: palette.navy, borderRadius: 24, padding: 22, minHeight: 142, justifyContent: 'flex-end', ...shadow },
  eyebrow: { color: '#FDBA74', fontSize: 12, fontWeight: '800', letterSpacing: 1.3, marginBottom: 8, textTransform: 'uppercase' },
  heroTitle: { color: 'white', fontSize: 28, lineHeight: 32, fontWeight: '900' },
  heroSubtitle: { color: '#D0D5DD', fontSize: 14, lineHeight: 20, marginTop: 8 },
  card: { backgroundColor: palette.surface, borderRadius: 18, borderWidth: 1, borderColor: palette.line, padding: 16, ...shadow },
  field: { height: 52, borderWidth: 1, borderColor: '#D0D5DD', borderRadius: 13, backgroundColor: 'white', paddingHorizontal: 15, color: palette.ink, fontSize: 16 },
  button: { minHeight: 50, borderRadius: 13, backgroundColor: palette.orange, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 18 },
  buttonText: { color: 'white', fontWeight: '800', fontSize: 15 },
  secondaryButton: { backgroundColor: 'white', borderWidth: 1, borderColor: palette.line },
  secondaryButtonText: { color: palette.ink },
  dangerButton: { backgroundColor: palette.red },
  sectionTitle: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 2 },
  sectionTitleText: { color: palette.ink, fontSize: 19, fontWeight: '900' },
  empty: { alignItems: 'center', paddingVertical: 28 },
  emptyTitle: { color: palette.ink, fontSize: 16, fontWeight: '800', marginBottom: 5 },
  body: { color: palette.muted, textAlign: 'center', lineHeight: 20 },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: palette.canvas },
});
