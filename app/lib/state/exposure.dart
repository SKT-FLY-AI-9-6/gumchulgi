import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/models.dart';

class ExposureController extends Notifier<Exposure?> {
  @override
  Exposure? build() => null;
  void update(Exposure e) => state = e;
}

final exposureProvider =
    NotifierProvider<ExposureController, Exposure?>(ExposureController.new);
