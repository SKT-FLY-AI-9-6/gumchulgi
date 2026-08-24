import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state/auth.dart';
import '../theme.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});
  @override
  ConsumerState<LoginScreen> createState() => _LoginState();
}

class _LoginState extends ConsumerState<LoginScreen> {
  final _email = TextEditingController();
  final _pw = TextEditingController();
  final _nick = TextEditingController();
  bool _signup = false;

  @override
  void dispose() {
    _email.dispose();
    _pw.dispose();
    _nick.dispose();
    super.dispose();
  }

  String _errorText(Object? e) {
    if (e is DioException) {
      final code = e.response?.statusCode;
      if (code == 409) return '이미 가입된 이메일입니다 — "로그인으로"를 눌러 로그인하세요';
      if (code == 401) return '비밀번호가 틀렸습니다';
      if (code == 422) return '입력을 확인하세요 (비밀번호 8자 이상, 이메일 형식)';
      if (e.response == null) return '서버에 연결할 수 없습니다 — 같은 와이파이인지 확인하세요';
    }
    return '실패: 이메일/비밀번호를 확인하세요';
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    return Scaffold(
      body: Center(child: SingleChildScrollView(
        padding: const EdgeInsets.all(32),
        child: Column(children: [
          const Text('SoftReel', style: TextStyle(
              fontSize: 32, fontWeight: FontWeight.bold)),
          const Text('광과민성 안전 숏폼 플랫폼',
              style: TextStyle(color: AppColors.sub)),
          const SizedBox(height: 32),
          TextField(controller: _email, decoration:
              const InputDecoration(labelText: '이메일')),
          TextField(controller: _pw, obscureText: true,
              decoration: const InputDecoration(labelText: '비밀번호 (8자+)')),
          if (_signup)
            TextField(controller: _nick, decoration:
                const InputDecoration(labelText: '닉네임')),
          const SizedBox(height: 24),
          if (auth.hasError)
            Padding(padding: const EdgeInsets.only(bottom: 8),
                child: Text(_errorText(auth.error),
                    style: const TextStyle(color: AppColors.red))),
          FilledButton(
            onPressed: auth.isLoading ? null : () {
              final n = ref.read(authProvider.notifier);
              _signup
                  ? n.signup(_email.text.trim(), _pw.text, _nick.text.trim())
                  : n.login(_email.text.trim(), _pw.text);
            },
            child: Text(_signup ? '가입하기' : '로그인')),
          TextButton(
            onPressed: () => setState(() => _signup = !_signup),
            child: Text(_signup ? '로그인으로' : '계정이 없나요? 가입')),
        ]),
      )),
    );
  }
}
