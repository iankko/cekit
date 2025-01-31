import pytest
import yaml

from cekit.config import Config
from cekit.errors import CekitError
from cekit.descriptor import Label, Port, Env, Volume, Packages, Image, Osbs, \
    Repository


config = Config()
config.configure('/dev/null', {'redhat': True})


def test_label():
    label = Label(yaml.safe_load("""
      name: "io.k8s.display-name"
      value: "JBoss A-MQ 6.2"
"""))
    assert label['name'] == "io.k8s.display-name"
    assert label['value'] == "JBoss A-MQ 6.2"


def test_env():
    env = Env(yaml.safe_load("""
      name: "io.k8s.display-name"
      value: "JBoss A-MQ 6.2"
"""))
    assert env['name'] == "io.k8s.display-name"
    assert env['value'] == "JBoss A-MQ 6.2"


def test_port():
    env = Port(yaml.safe_load("""
      value: 8788
      expose: False
"""))
    assert env['value'] == 8788
    assert env['name'] == 8788
    assert not env['expose']


def test_volume():
    volume = Volume(yaml.safe_load("""
    name: vol1
    path: /tmp/a
"""))
    assert volume['name'] == 'vol1'
    assert volume['path'] == '/tmp/a'


def test_volume_name():
    volume = Volume(yaml.safe_load("""
    path: /tmp/a
"""))
    assert volume['name'] == 'a'
    assert volume['path'] == '/tmp/a'


def test_osbs():
    osbs = Osbs(yaml.safe_load("""
    repository:
      name: foo
      branch: bar
"""), "a/path/image.yaml")

    assert osbs['repository']['name'] == 'foo'
    assert osbs['repository']['branch'] == 'bar'


def test_packages():
    pkg = Packages(yaml.safe_load("""
      install:
          - pkg-foo"""), "a/path/image.yaml")

    assert 'pkg-foo' in pkg['install']


def test_packages_invalid_old_repository_definition():
    with pytest.raises(CekitError, match=r"Cannot validate schema: Repository"):
        Packages(yaml.safe_load("""
        repositories:
            - repo-foo
            - repo-bar
        install:
            - pkg-foo"""), "a/path/image.yaml")


def test_packages_content_sets_and_content_sets_file():
    with pytest.raises(CekitError, match=r"You cannot specify 'content_sets' and 'content_sets_file' together in the packages section!"):
        Packages(
            {
                'content_sets': {
                    'x86_64': ['rhel-server-rhscl-7-rpms', 'rhel-7-server-rpms']
                },
                'content_sets_file': "a_path.yaml"
            },
            "a/path"
        )


def test_packages_content_sets():
    pkg = Packages(
        {
            'content_sets': {
                'x86_64': ['rhel-server-rhscl-7-rpms', 'rhel-7-server-rpms']
            },
            'install': ['package_a', 'package_b']
        },
        "a/path"
    )

    assert 'package_a' in pkg['install']
    assert 'content_sets_file' not in pkg


def test_packages_content_sets_file(mocker):
    with mocker.mock_module.patch('cekit.descriptor.packages.os.path.exists') as exists_mock:
        exists_mock.return_value = True
        with mocker.mock_module.patch('cekit.descriptor.packages.open', mocker.mock_open(read_data='{"a": 12}')):
            pkg = Packages(
                {
                    'content_sets_file': "a_path.yaml",
                    'install': ['package_a', 'package_b']
                },
                "a/path"
            )

    assert 'package_a' in pkg['install']
    assert 'content_sets_file' not in pkg
    assert pkg['content_sets'] == {'a': 12}


def test_image():
    image = Image(yaml.safe_load("""
    from: foo
    name: test/foo
    version: 1.9
    labels:
      - name: test
        value: val1
      - name: label2
        value: val2
    envs:
      - name: env1
        value: env1val
    """), 'foo')

    assert image['name'] == 'test/foo'
    assert type(image['labels'][0]) == Label
    assert image['labels'][0]['name'] == 'test'


def test_image_missing_name():
    with pytest.raises(CekitError):
        Image(yaml.safe_load("""
        from: foo
        version: 1.9"""), 'foo')


def test_remove_none_key():
    image = Image(yaml.safe_load("""
    from: foo
    name: test/foo
    version: 1.9
    envs:
     - name: foo
       value: ~
    """), 'foo')
    image.remove_none_keys()

    assert 'envs' in image
    assert 'value' not in image['envs'][0]
