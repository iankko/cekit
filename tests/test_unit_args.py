import importlib
import pytest

from click.testing import CliRunner

from cekit.cli import cli




def get_class_by_name(clazz):
    module_name, class_name = clazz.rsplit('.', 1)

    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)

    return cls


@pytest.mark.parametrize('args,clazz,common_params,params', [
    # Check custom target
    (
        ['--redhat', 'build', 'docker'],
        'cekit.builders.docker_builder.DockerBuilder',
        {
            'descriptor': 'image.yaml', 'verbose': False, 'work_dir': '~/.cekit', 'config': '~/.cekit/config', 'redhat': True, 'target': 'target'
        },
        {
            'validate': False, 'dry_run': False, 'overrides': (), 'pull': False, 'no_squash': False, 'tags': ()
        }
    ),
    # Check custom target
    (
        ['--target', 'custom-target', 'build', 'docker'],
        'cekit.builders.docker_builder.DockerBuilder',
        {
            'descriptor': 'image.yaml', 'verbose': False, 'work_dir': '~/.cekit', 'config': '~/.cekit/config', 'redhat': False, 'target': 'custom-target'
        },
        {
            'validate': False, 'dry_run': False, 'overrides': (), 'pull': False, 'no_squash': False, 'tags': ()
        }
    ),
    # Check custom work dir
    (
        ['--work-dir', 'custom-workdir', 'build', 'docker'],
        'cekit.builders.docker_builder.DockerBuilder',
        {
            'descriptor': 'image.yaml', 'verbose': False, 'work_dir': 'custom-workdir', 'config': '~/.cekit/config', 'redhat': False, 'target': 'target'
        },
        {
            'validate': False, 'dry_run': False, 'overrides': (), 'pull': False, 'no_squash': False, 'tags': ()
        }
    ),
    # Check custom config file
    (
        ['--config', 'custom-config', 'build', 'docker'],
        'cekit.builders.docker_builder.DockerBuilder',
        {
            'descriptor': 'image.yaml', 'verbose': False, 'work_dir': '~/.cekit', 'config': 'custom-config', 'redhat': False, 'target': 'target'
        },
        {
            'validate': False, 'dry_run': False, 'overrides': (),  'pull': False, 'no_squash': False, 'tags': ()
        }
    ),
    # Test default values for Docker builder
    (
        ['build', 'docker'],
        'cekit.builders.docker_builder.DockerBuilder',
        None,
        {
            'validate': False, 'dry_run': False, 'overrides': (), 'pull': False, 'no_squash': False, 'tags': ()
        }
    ),
    # Test overrides
    (
        ['build', '--overrides', 'foo', '--overrides-file', 'bar', 'docker'],
        'cekit.builders.docker_builder.DockerBuilder',
        None,
        {
            'validate': False, 'dry_run': False, 'overrides': ('foo', 'bar'), 'pull': False, 'no_squash': False, 'tags': ()
        }
    ),
    # Test default values for OSBS builder
    (
        ['build', 'osbs'],
        'cekit.builders.osbs.OSBSBuilder',
        None,
        {
            'validate': False, 'dry_run': False, 'overrides': (), 'nowait': False, 'release': False, 'tech_preview': False, 'user': None, 'stage': False, 'koji_target': None, 'commit_message': None
        }
    ),
    # Test setting user for OSBS
    (
        ['build', 'osbs', '--user', 'SOMEUSER'],
        'cekit.builders.osbs.OSBSBuilder',
        None,
        {
            'validate': False, 'dry_run': False, 'overrides': (), 'nowait': False, 'release': False, 'tech_preview': False, 'user': 'SOMEUSER', 'stage': False, 'koji_target': None, 'commit_message': None
        }
    ),
    # Test setting stage environment for OSBS
    (
        ['build', 'osbs', '--stage'],
        'cekit.builders.osbs.OSBSBuilder',
        None,
        {
            'validate': False, 'dry_run': False, 'overrides': (), 'nowait': False, 'release': False, 'tech_preview': False, 'user': None, 'stage': True, 'koji_target': None, 'commit_message': None
        }
    ),
    # Test setting nowait for OSBS
    (
        ['build', 'osbs', '--nowait'],
        'cekit.builders.osbs.OSBSBuilder',
        None,
        {
            'validate': False, 'dry_run': False, 'overrides': (), 'nowait': True, 'release': False, 'tech_preview': False, 'user': None, 'stage': False, 'koji_target': None, 'commit_message': None
        }
    ),
    (
        ['test', '--image', 'image:1.0', 'behave'],
        'cekit.test.behave_tester.BehaveTester',
        {
            'descriptor': 'image.yaml', 'verbose': False, 'work_dir': '~/.cekit', 'config': '~/.cekit/config', 'redhat': False, 'target': 'target'
        },
        {
            'overrides': (), 'image': 'image:1.0', 'steps_url': 'https://github.com/cekit/behave-test-steps.git', 'wip': False, 'names': ()
        }
    ),
    (
        ['build', 'docker', '--pull'],
        'cekit.builders.docker_builder.DockerBuilder',
        None,
        {
            'validate': False, 'dry_run': False, 'overrides': (), 'pull': True, 'no_squash': False, 'tags': ()
        }
    ),
    (
        ['build', 'osbs'],
        'cekit.builders.osbs.OSBSBuilder',
        None,
        {
            'validate': False, 'dry_run': False, 'overrides': (), 'release': False, 'tech_preview': False, 'user': None, 'nowait': False, 'stage': False, 'koji_target': None, 'commit_message': None
        }),
    (
        ['build', 'docker'],
        'cekit.builders.docker_builder.DockerBuilder',
        None,
        {
            'validate': False, 'dry_run': False, 'overrides': (), 'pull': False, 'no_squash': False, 'tags': ()
        }
    ),
    (
        ['build', 'buildah'],
        'cekit.builders.buildah.BuildahBuilder',
        None,
        {
            'validate': False, 'dry_run': False, 'overrides': (), 'pull': False, 'tags': ()
        }
    )
])
def test_args_command(mocker, args, clazz, common_params, params):
    if not common_params:
        common_params = {
            'descriptor': 'image.yaml', 'verbose': False, 'work_dir': '~/.cekit',
            'config': '~/.cekit/config', 'redhat': False, 'target': 'target'
        }

    cekit_class = mocker.patch('cekit.cli.Cekit')
    cekit_object = mocker.Mock()
    cekit_class.return_value = cekit_object
    CliRunner().invoke(cli, args, catch_exceptions=False)

    cls = get_class_by_name(clazz)

    cekit_class.assert_called_once_with(common_params)
    cekit_object.run.assert_called_once_with(cls, params)


def test_args_not_valid_command():
    result = CliRunner().invoke(cli, ['explode'], catch_exceptions=False)

    assert isinstance(result.exception, SystemExit)
    assert 'No such command "explode"' in result.output
    assert result.exit_code == 2


def test_args_invalid_build_engine():
    result = CliRunner().invoke(cli, ['build', 'rocketscience'], catch_exceptions=False)

    assert isinstance(result.exception, SystemExit)
    assert 'No such command "rocketscience"' in result.output
    assert result.exit_code == 2
