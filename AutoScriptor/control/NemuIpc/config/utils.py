import json
import os
import random
import string
from datetime import datetime, timedelta, timezone

import yaml


LANGUAGES = ['zh-CN', 'en-US', 'ja-JP', 'zh-TW', 'es-ES']
SERVER_TO_TIMEZONE = {
    'CN-Official': timedelta(hours=8),
    'CN-Bilibili': timedelta(hours=8),
    'OVERSEA-America': timedelta(hours=-5),
    'OVERSEA-Asia': timedelta(hours=8),
    'OVERSEA-Europe': timedelta(hours=1),
    'OVERSEA-TWHKMO': timedelta(hours=8),
}
DEFAULT_TIME = datetime(2020, 1, 1, 0, 0)


# https://stackoverflow.com/questions/8640959/how-can-i-control-what-scalar-form-pyyaml-uses-for-my-data/15423007
def str_presenter(dumper, data):
    if len(data.splitlines()) > 1:  # check for multiline string
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)


def filepath_args(filename='args', mod_name='alas'):
    return f'./module/config/argument/{filename}.json'


def filepath_argument(filename):
    return f'./module/config/argument/{filename}.yaml'


def filepath_i18n(lang, mod_name='alas'):
    return os.path.join('./module/config/i18n', f'{lang}.json')


def filepath_config(filename, mod_name='alas'):
    if mod_name == 'alas':
        return os.path.join('./config', f'{filename}.json')
    else:
        return os.path.join('./config', f'{filename}.{mod_name}.json')


def filepath_code():
    return './module/config/config_generated.py'


def iter_folder(folder, is_dir=False, ext=None):
    """
    Args:
        folder (str):
        is_dir (bool): True to iter directories only
        ext (str): File extension, such as `.yaml`

    Yields:
        str: Absolute path of files
    """
    for file in os.listdir(folder):
        sub = os.path.join(folder, file)
        if is_dir:
            if os.path.isdir(sub):
                yield sub.replace('\\\\', '/').replace('\\', '/')
        elif ext is not None:
            if not os.path.isdir(sub):
                _, extension = os.path.splitext(file)
                if extension == ext:
                    yield os.path.join(folder, file).replace('\\\\', '/').replace('\\', '/')
        else:
            yield os.path.join(folder, file).replace('\\\\', '/').replace('\\', '/')


def alas_template():
    """
        Returns:
            list[str]: Name of all Alas instances, except `template`.
        """
    out = []
    for file in os.listdir('./config'):
        name, extension = os.path.splitext(file)
        if name == 'template' and extension == '.json':
            out.append(f'{name}-src')

    # out.extend(mod_template())

    return out


def alas_instance():
    """
    Returns:
        list[str]: Name of all Alas instances, except `template`.
    """
    out = []
    for file in os.listdir('./config'):
        name, extension = os.path.splitext(file)
        config_name, mod_name = os.path.splitext(name)
        mod_name = mod_name[1:]
        if name != 'template' and extension == '.json' and mod_name == '':
            out.append(name)

    # out.extend(mod_instance())

    if not len(out):
        out = ['src']

    return out


def parse_value(value, data):
    """
    Convert a string to float, int, datetime, if possible.

    Args:
        value (str):
        data (dict):

    Returns:

    """
    if 'option' in data:
        if value not in data['option']:
            return data['value']
    if isinstance(value, str):
        if value == '':
            return None
        if value == 'true' or value == 'True':
            return True
        if value == 'false' or value == 'False':
            return False
        if '.' in value:
            try:
                return float(value)
            except ValueError:
                pass
        else:
            try:
                return int(value)
            except ValueError:
                pass
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass

    return value


def data_to_type(data, **kwargs):
    """
    | Condition                            | Type     |
    | ------------------------------------ | -------- |
    | `value` is bool                      | checkbox |
    | Arg has `options`                    | select   |
    | Arg has `stored`                     | select   |
    | `Filter` is in name (in data['arg']) | textarea |
    | Rest of the args                     | input    |

    Args:
        data (dict):
        kwargs: Any additional properties

    Returns:
        str:
    """
    kwargs.update(data)
    if isinstance(kwargs.get('value'), bool):
        return 'checkbox'
    elif 'option' in kwargs and kwargs['option']:
        return 'select'
    elif 'stored' in kwargs and kwargs['stored']:
        return 'stored'
    elif 'Filter' in kwargs['arg']:
        return 'textarea'
    else:
        return 'input'


def data_to_path(data):
    """
    Args:
        data (dict):

    Returns:
        str: <func>.<group>.<arg>
    """
    return '.'.join([data.get(attr, '') for attr in ['func', 'group', 'arg']])


def path_to_arg(path):
    """
    Convert dictionary keys in .yaml files to argument names in config.

    Args:
        path (str): Such as `Scheduler.ServerUpdate`

    Returns:
        str: Such as `Scheduler_ServerUpdate`
    """
    return path.replace('.', '_')


def dict_to_kv(dictionary, allow_none=True):
    """
    Args:
        dictionary: Such as `{'path': 'Scheduler.ServerUpdate', 'value': True}`
        allow_none (bool):

    Returns:
        str: Such as `path='Scheduler.ServerUpdate', value=True`
    """
    return ', '.join([f'{k}={repr(v)}' for k, v in dictionary.items() if allow_none or v is not None])



def random_normal_distribution_int(a, b, n=3):
    """
    A non-numpy implementation of the `random_normal_distribution_int` in module.base.utils


    Generate a normal distribution int within the interval.
    Use the average value of several random numbers to
    simulate normal distribution.

    Args:
        a (int): The minimum of the interval.
        b (int): The maximum of the interval.
        n (int): The amount of numbers in simulation. Default to 3.

    Returns:
        int
    """
    if a < b:
        output = sum([random.randint(a, b) for _ in range(n)]) / n
        return int(round(output))
    else:
        return b


def ensure_time(second, n=3, precision=3):
    """Ensure to be time.

    Args:
        second (int, float, tuple): time, such as 10, (10, 30), '10, 30'
        n (int): The amount of numbers in simulation. Default to 5.
        precision (int): Decimals.

    Returns:
        float:
    """
    if isinstance(second, tuple):
        multiply = 10 ** precision
        return random_normal_distribution_int(second[0] * multiply, second[1] * multiply, n) / multiply
    elif isinstance(second, str):
        if ',' in second:
            lower, upper = second.replace(' ', '').split(',')
            lower, upper = int(lower), int(upper)
            return ensure_time((lower, upper), n=n, precision=precision)
        if '-' in second:
            lower, upper = second.replace(' ', '').split('-')
            lower, upper = int(lower), int(upper)
            return ensure_time((lower, upper), n=n, precision=precision)
        else:
            return int(second)
    else:
        return second

