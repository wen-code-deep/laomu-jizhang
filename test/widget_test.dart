import 'package:flutter_test/flutter_test.dart';

import 'package:laomu_jizhang/main.dart';

void main() {
  testWidgets('App starts and shows splash screen', (WidgetTester tester) async {
    await tester.pumpWidget(const LaomuApp());

    // 启动画面应该显示"老母记账"标题
    expect(find.text('老母记账'), findsOneWidget);
  });
}
