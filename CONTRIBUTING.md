# Contributing to pdp

Thank you for taking the time to contribute to pdp!

Any kind of contribution is encouraged and appreciated. See the
[Table of Contents](#table-of-contents) for different ways to help and details
about how this project handles them.

> If you like the project, but don't have time to contribute, that's still
> great. There are other easy ways to support the work and show your
> appreciation, which we would encourage:
>
> - Use it!
> - Star the repository
> - Recommend it to others
> - Socially media about it if you must

## Table of Contents

- [Questions](#questions)
- [How to Contribute](#how-to-contribute)
- [Report Bugs](#report-bugs)
- [Suggest Enhancements](#suggest-enhancements)
- [Pull Requests](#pull-requests)

## Questions

This project is still nascent, so proper documentation and tutorials are still
being developed. Be sure to check the [README](README.md) for basics on setting
up and using pdp. Also, please check the
[Issues](https://github.com/scienceandhumanitylab/pdp/issues) in case someone
has asked a similar question already.

If you can't find what you're looking for, open a new issue:

- Open a
  [New Issue](https://github.com/scienceandhumanitylab/pdp/issues/new/choose).
- Provide as much context as you can about what you're running into.
- Provide project and platform versions (nodejs, npm, etc), depending on what
  seems relevant.

We will then take care of the issue as soon as possible.

## How to Contribute

### Report Bugs

#### Before Submitting a Bug Report

A good bug report should contain all the necessary information to reproduce the
problem.

shouldn't leave others needing to chase you up for more information. Therefore,
we ask you to investigate carefully, collect information and describe the issue
in detail in your report. Please complete the following steps in advance to help
us fix any potential bug as fast as possible.

- Make sure that you are using the latest version of pdp.
- Check if your bug might be an error due to incompatible environments or
  versions
- See if other have experienced or solved the same issue you are having, by
  looking at the
  [bug tracker](https://github.com/scienceandhumanitylab/pdp/issues?q=label%3Abug).
- Collect information about the bug:
- Stack trace (Traceback)
- OS, Platform and Version (Windows, Linux, macOS, x86, ARM)
- Version of the interpreter, compiler, SDK, runtime environment, package
  manager, depending on what seems relevant.
- Possibly your input and the output
- Can you reliably reproduce the issue? And can you also reproduce it with older
  versions?

#### How Do I Submit a Good Bug Report?

> Please do not must report security related issues, vulnerabilities or bugs
> including sensitive information to the issues, discussion, or anywhere public.
> Sensitive bugs must be sent by email to <christopher.donovan@uvm.edu>.

We use GitHub issues to track bugs and errors. If you run into an issue with the
project:

- Open an [Issue](https://github.com/scienceandhumanitylab/pdp/issues). (Since
  we can't be sure at this point whether it is a bug or not, we ask you not to
  talk about a bug yet and not to label the issue.)
- Explain the behavior you would expect and the actual behavior.
- Please provide as much context as possible and describe the _reproduction
  steps_ that someone else can follow to recreate the issue on their own. This
  usually includes your code. For good bug reports you should isolate the
  problem and create a reduced test case.
- Provide the information you collected in the previous section.

Once it's filed:

- The project team will label the issue accordingly.
- A team member will try to reproduce the issue with your provided steps. If
  there are no reproduction steps or no obvious way to reproduce the issue, the
  team will ask you for those steps and mark the issue as `needs-repro`. Bugs
  with the `needs-repro` tag will not be addressed until they are reproduced.

### Suggest Enhancements

This section guides you through submitting an enhancement suggestion for
CONTRIBUTING.md, **including completely new features and minor improvements to
existing functionality**. Following these guidelines will help maintainers and
the community to understand your suggestion and find related suggestions.

#### Before Submitting an Enhancement

- Make sure that you are using the latest version.
- Run a [search](https://github.com/scienceandhumanitylab/pdp/issues) to see if
  the enhancement has already been suggested. If it has, add a comment to the
  existing issue instead of opening a new one.
- Find out whether your idea fits with the scope and aims of the project. It's
  up to you to make a strong case to convince the project's developers of the
  merits of this feature.

#### How Do I Submit a Good Enhancement Suggestion?

Enhancement suggestions are tracked as
[GitHub Issues](https://github.com/scienceandhumanitylab/pdp/issues/new/choose).

- Use a **clear and descriptive title** for the issue to identify the
  suggestion.
- Provide a **step-by-step description of the suggested enhancement** in as many
  details as possible.
- **Describe the current behavior** and **explain which behavior you expected to
  see instead** and why. At this point you can also tell which alternatives do
  not work for you.
- You may want to **include screenshots and animated GIFs** which help you
  demonstrate the steps or point out the part which the suggestion is related
  to.
- **Explain why this enhancement would be useful** to most CONTRIBUTING.md
  users. You may also want to point out the other projects that solved it better
  and which could serve as inspiration.

### Pull Requests

Thank you for being willing to contribute code to the project. We very much
appreciate you. **Before opening a pull request, please start with an issue,
discussion, or email**. The project is changing relatively quickly, and we would
like to be aligned in terms of motivation and direction before anyone spends the
time to write up a request. We may already have plans for the work you're
adding, or have already considered it and decided against it. The best way to
make sure we respect the time and effort of the community is to have a
conversation first. The bar for questions and discussions is very low, so please
reach out!

#### Style Guide

If you submit a pull request, please:

- Run tests with [Pytest](https://docs.pytest.org/en/stable/) (`uv run pytest`).
- Format code with [Ruff](https://github.com/astral-sh/ruff), and format
  markdown files with [Prettier](https://prettier.io/)
- Use
  [Google style docstrings](https://google.github.io/styleguide/pyguide.html#docstrings).

## Attribution

This guide is based on the **contributing.md**.
[Make your own](https://contributing.md/)!
