import 'dart:convert';

/// 预设的支出分类
class ExpenseCategory {
  final String name;
  final String icon;

  const ExpenseCategory(this.name, this.icon);

  static const List<ExpenseCategory> expenseCategories = [
    ExpenseCategory('餐饮', '🍜'),
    ExpenseCategory('交通', '🚗'),
    ExpenseCategory('购物', '🛒'),
    ExpenseCategory('住房', '🏠'),
    ExpenseCategory('水电燃气', '⚡'),
    ExpenseCategory('医疗健康', '🏥'),
    ExpenseCategory('教育学习', '📚'),
    ExpenseCategory('娱乐休闲', '🎮'),
    ExpenseCategory('通讯网络', '📱'),
    ExpenseCategory('服饰美容', '👗'),
    ExpenseCategory('日用百货', '🧴'),
    ExpenseCategory('其他', '📦'),
  ];

  /// 预设的收入分类
  static const List<ExpenseCategory> incomeCategories = [
    ExpenseCategory('工资', '💼'),
    ExpenseCategory('兼职', '💪'),
    ExpenseCategory('投资理财', '📈'),
    ExpenseCategory('红包礼金', '🧧'),
    ExpenseCategory('退款', '↩️'),
    ExpenseCategory('其他收入', '💰'),
  ];
}

/// 一笔账目记录（可以是支出或收入）
class Expense {
  final String id;
  final double amount;
  final String categoryName;
  final DateTime date;
  final String? note;
  final bool isExpense; // true = 支出, false = 收入

  const Expense({
    required this.id,
    required this.amount,
    required this.categoryName,
    required this.date,
    this.note,
    this.isExpense = true, // 默认支出
  });

  /// 获取分类对象（含图标）
  ExpenseCategory get category {
    final list =
        isExpense ? ExpenseCategory.expenseCategories : ExpenseCategory.incomeCategories;
    return list.firstWhere(
      (c) => c.name == categoryName,
      orElse: () => isExpense
          ? const ExpenseCategory('其他', '📦')
          : const ExpenseCategory('其他收入', '💰'),
    );
  }

  /// 交易类型文字
  String get typeLabel => isExpense ? '支出' : '收入';

  /// 转为 JSON
  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'amount': amount,
      'categoryName': categoryName,
      'date': date.toIso8601String(),
      'note': note ?? '',
      'isExpense': isExpense,
    };
  }

  /// 从 JSON 还原
  factory Expense.fromJson(Map<String, dynamic> json) {
    return Expense(
      id: json['id'] as String,
      amount: (json['amount'] as num).toDouble(),
      categoryName: json['categoryName'] as String,
      date: DateTime.parse(json['date'] as String),
      note: (json['note'] as String).isEmpty ? null : json['note'] as String,
      isExpense: json['isExpense'] as bool? ?? true,
    );
  }

  /// 列表 → JSON 字符串
  static String listToJson(List<Expense> expenses) {
    return jsonEncode(expenses.map((e) => e.toJson()).toList());
  }

  /// JSON 字符串 → 列表
  static List<Expense> listFromJson(String jsonStr) {
    final list = jsonDecode(jsonStr) as List<dynamic>;
    return list.map((e) => Expense.fromJson(e as Map<String, dynamic>)).toList();
  }
}
