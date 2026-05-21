namespace WaiComputer.Core.Auth;

/// <summary>
/// Encrypts session bytes at rest. On Windows this is backed by DPAPI
/// (<c>System.Security.Cryptography.ProtectedData</c>, CurrentUser scope).
/// A null-protector ("plaintext") implementation is allowed only inside test
/// fixtures — never in production code paths.
/// </summary>
public interface ISessionProtector
{
    byte[] Protect(byte[] plaintext);
    byte[] Unprotect(byte[] ciphertext);
}

/// <summary>
/// Identity protector. Reserved for test code where exercising the encryption
/// path adds no value (e.g., parser tests). Production must use a real DPAPI
/// or AES-backed implementation; relying on this in shipped code would
/// effectively store tokens in plaintext.
/// </summary>
internal sealed class NullSessionProtector : ISessionProtector
{
    public byte[] Protect(byte[] plaintext) => plaintext;
    public byte[] Unprotect(byte[] ciphertext) => ciphertext;
}

/// <summary>
/// DPAPI-backed protector. Available on every supported runtime via the
/// <c>System.Security.Cryptography.ProtectedData</c> NuGet package; throws
/// <see cref="PlatformNotSupportedException"/> on non-Windows hosts.
/// </summary>
public sealed class DpapiSessionProtector : ISessionProtector
{
    private readonly byte[] _entropy;

    public DpapiSessionProtector(byte[]? entropy = null)
    {
        _entropy = entropy ?? Array.Empty<byte>();
    }

    public byte[] Protect(byte[] plaintext)
    {
        return System.Security.Cryptography.ProtectedData.Protect(
            plaintext,
            _entropy,
            System.Security.Cryptography.DataProtectionScope.CurrentUser);
    }

    public byte[] Unprotect(byte[] ciphertext)
    {
        return System.Security.Cryptography.ProtectedData.Unprotect(
            ciphertext,
            _entropy,
            System.Security.Cryptography.DataProtectionScope.CurrentUser);
    }
}
