import 'package:flutter/material.dart';

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext c) => Scaffold(
      appBar: AppBar(title: const Text('광 노출 대시보드')),
      body: const Center(child: Text('대시보드')));
}
