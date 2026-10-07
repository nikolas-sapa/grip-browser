import pytest

from grip.errors.types import ErrorType, GripError
from grip.security.policy import NavigationPolicy, enforce


MAPPED_METADATA = (
    '::ffff:169.254.169.254',
    '::ffff:a9fe:a9fe',
    '::ffff:169.254.170.2',
    '::ffff:a9fe:aa02',
)


@pytest.mark.parametrize('host', MAPPED_METADATA)
@pytest.mark.parametrize('scheme', ('http', 'https'))
@pytest.mark.parametrize('allow_private', (False, True))
def test_mapped_metadata_always_refused(host, scheme, allow_private):
    policy = NavigationPolicy(allow_private=allow_private)
    url = f'{scheme}://[{host}]/'
    assert 'metadata' in (policy.check(url) or '')
    with pytest.raises(GripError) as caught:
        enforce(policy, url)
    assert caught.value.error.type == ErrorType.NAVIGATION_REFUSED


@pytest.mark.parametrize('host', ('::ffff:127.0.0.1', '::ffff:7f00:1'))
def test_mapped_loopback_opt_in_preserved(host):
    url = f'http://[{host}]/'
    assert NavigationPolicy().check(url) is not None
    assert NavigationPolicy(allow_private=True).check(url) is None


@pytest.mark.parametrize(
    'host', ('169.254.169.254.', '169.254.170.2.', 'metadata.google.internal.')
)
@pytest.mark.parametrize('scheme', ('http', 'https'))
@pytest.mark.parametrize('allow_private', (False, True))
def test_metadata_dns_root_dot_always_refused(host, scheme, allow_private):
    reason = NavigationPolicy(allow_private=allow_private).check(f'{scheme}://{host}/')
    assert 'metadata' in (reason or '')


@pytest.mark.parametrize('host', ('localhost.', 'test.localhost.'))
def test_localhost_dns_root_dot_preserves_private_opt_in(host):
    url = f'http://{host}/'
    assert NavigationPolicy().check(url) is not None
    assert NavigationPolicy(allow_private=True).check(url) is None
