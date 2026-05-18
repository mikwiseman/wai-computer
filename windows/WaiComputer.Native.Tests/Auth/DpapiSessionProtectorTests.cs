using FluentAssertions;
using System.Security.Cryptography;
using WaiComputer.Core.Auth;
using Xunit;

namespace WaiComputer.Native.Tests.Auth;

public class DpapiSessionProtectorTests
{
    [Fact]
    public void RoundTrip()
    {
        var protector = new DpapiSessionProtector();
        var plain = "the-quick-brown-fox"u8.ToArray();
        var cipher = protector.Protect(plain);
        cipher.Should().NotEqual(plain);

        var recovered = protector.Unprotect(cipher);
        recovered.Should().Equal(plain);
    }

    [Fact]
    public void EntropyChangesCiphertext()
    {
        var a = new DpapiSessionProtector(entropy: "salt-a"u8.ToArray());
        var b = new DpapiSessionProtector(entropy: "salt-b"u8.ToArray());
        var plain = "secret"u8.ToArray();
        a.Protect(plain).Should().NotEqual(b.Protect(plain));
    }

    [Fact]
    public void TamperedCiphertextThrows()
    {
        var protector = new DpapiSessionProtector();
        var cipher = protector.Protect("hi"u8.ToArray());
        cipher[0] ^= 0xFF;
        Action act = () => protector.Unprotect(cipher);
        act.Should().Throw<CryptographicException>();
    }
}
