import Foundation

/// Russian plural selection: 1 запись / 2 записи / 5 записей.
/// English needs only one/many; Russian needs one/few/many with the 11–14 rule.
public enum RussianPlural {
    public static func form(_ count: Int, one: String, few: String, many: String) -> String {
        let n = abs(count) % 100
        if (11...14).contains(n) { return many }
        switch n % 10 {
        case 1: return one
        case 2...4: return few
        default: return many
        }
    }
}
