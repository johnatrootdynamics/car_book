import { StyleSheet, View } from 'react-native';
import Svg, { Image } from 'react-native-svg';

// Display the approved artwork, trimming its presentation margins in the viewport.
export function BrandLogo({ width = 230 }: { width?: number }) {
  return <View accessible accessibilityRole="image" accessibilityLabel="Track ops" style={[styles.logo, { width }]}>
    <Svg width="100%" height="100%" viewBox="140 190 1900 350">
      <Image href={require('@/assets/brand/track-ops-logo.png')} width={2172} height={724} />
    </Svg>
  </View>;
}

const styles = StyleSheet.create({
  logo: { maxWidth: '100%', aspectRatio: 1900 / 350, overflow: 'hidden' },
});
