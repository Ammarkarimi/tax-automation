import { Text } from 'react-native'
import { Redirect, Tabs } from 'expo-router'
import { useAuth } from '../../lib/auth'
import { Loading, colors } from '../../components/ui'

const icon = (emoji) => ({ focused }) => <Text style={{ fontSize: 20, opacity: focused ? 1 : 0.55 }}>{emoji}</Text>

export default function TabsLayout() {
  const { user, loading } = useAuth()
  if (loading) return <Loading />
  if (!user) return <Redirect href="/login" />
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: colors.brandDark },
        headerTintColor: colors.white,
        tabBarActiveTintColor: colors.brand,
      }}
    >
      <Tabs.Screen name="index" options={{ title: 'Home', tabBarIcon: icon('🏠') }} />
      <Tabs.Screen name="scan" options={{ title: 'Scan & Upload', tabBarLabel: 'Scan', tabBarIcon: icon('📷') }} />
      <Tabs.Screen name="transactions" options={{ title: 'Transactions', tabBarIcon: icon('📒') }} />
      <Tabs.Screen name="taxes" options={{ title: 'My Taxes', tabBarLabel: 'Taxes', tabBarIcon: icon('🧾') }} />
      <Tabs.Screen name="assistant" options={{ title: 'Ask TaxPilot', tabBarLabel: 'Ask', tabBarIcon: icon('💬') }} />
    </Tabs>
  )
}
