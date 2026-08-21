import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'screens/login.dart';
import 'screens/shell.dart';
import 'state/auth.dart';
import 'theme.dart';

void main() => runApp(const ProviderScope(child: App()));

class App extends ConsumerWidget {
  const App({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    return MaterialApp(
      title: '검출기', theme: appTheme,
      // 가로 화면(웹 데스크톱)에서는 쇼츠답게 가운데 9:16 프레임으로 제한.
      // 폰(세로 화면)은 그대로 전체 화면.
      builder: (context, child) => LayoutBuilder(builder: (context, box) {
        if (box.maxWidth <= box.maxHeight) return child!;
        return ColoredBox(
            color: Colors.black,
            child: Center(
                child: SizedBox(
                    width: box.maxHeight * 9 / 16, child: child)));
      }),
      home: auth.when(
        data: (u) => u == null ? const LoginScreen() : const ShellScreen(),
        loading: () => const Scaffold(
            body: Center(child: CircularProgressIndicator())),
        error: (_, __) => const LoginScreen()));
  }
}
